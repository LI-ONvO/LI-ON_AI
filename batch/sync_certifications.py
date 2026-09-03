"""자격증 참조 데이터 수집 스크립트.

공공데이터포털에서 자격증 목록·상세·시험일정을 받아 MySQL에 저장한다.
AI 서버는 이 테이블을 읽기만 하므로, 데이터를 채우거나 갱신할 때 이 스크립트를 직접 실행한다.

실행:
    python -m batch.sync_certifications

(주기적 자동 갱신은 나중에 붙인다. 지금은 실행할 때마다 한 번 최신화한다.)
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")

# 국가자격 종목 목록 (T:국가기술자격, S:국가전문자격)
NATIONAL_QUAL_URL = (
    "http://openapi.q-net.or.kr/api/service/rest/"
    "InquiryListNationalQualifcationSVC/getList"
)
# 국가기술자격 종목 상세 (진로·수행직무·개요·출제경향·변천과정)
QUAL_INFO_URL = "http://openapi.q-net.or.kr/api/service/rest/InquiryQualInfo/getList"
# 일학습병행자격 / 과정평가형자격 종목 목록
WJM_URL = "https://c.q-net.or.kr/openapi/wjmlist.do"
CJM_URL = "https://c.q-net.or.kr/openapi/cjmlist.do"
# 시험일정
EXAM_SCHD_URL = "http://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList"

# 이 API는 한 페이지 50건을 넘기면 resultCode 930으로 거절한다.
SCHEDULE_PAGE_SIZE = 50

# 상세정보 API의 계열코드. 산업기사는 전용 코드가 없고 03(기사)에 함께 들어온다.
SERIES_CODES = ("01", "02", "03", "04")

CERT_FIELDS = ["jm_cd", "jm_nm", "qual_gb_cd", "series_nm"]

DETAIL_FIELDS = ["jm_cd", "mdoblig_fld_nm", "career", "job", "summary", "trend", "hist"]

SCHEDULE_FIELDS = [
    "jm_cd", "impl_yy", "impl_seq", "doc_reg_start_dt", "description",
    "doc_reg_end_dt", "doc_exam_start_dt", "doc_exam_end_dt", "doc_pass_dt",
    "prac_reg_start_dt", "prac_reg_end_dt", "prac_exam_start_dt", "prac_exam_end_dt",
    "prac_pass_dt",
]

# 응답 텍스트 앞에 에디터가 남긴 CSS 조각이 그대로 붙어 있다. 형태가 두 가지다.
#   "BODY {...}P {...}LI {...}실제 내용"
#   "정보처리기능사 개요BODY {...}P {...}LI {...}실제 내용"   <- 종목명 라벨이 앞에 붙는 경우
# 같은 종목이라도 호출 시점에 따라 달라서 둘 다 걷어낸다.
# CSS 블록이 없으면 아무것도 지우지 않는다.
_STYLE_JUNK = re.compile(r"^[^{}]*?(?:[A-Za-z]+\s*\{[^{}]*\}\s*)+")


# --------------------------------------------------------------------------- API

# 상세 정보 API는 계열 하나가 수백 종목 x 항목당 최대 1만자라 응답이 매우 느리다.
# (기사 계열은 648KB, 실측 3분 이상) 넉넉하게 잡지 않으면 매번 타임아웃 난다.
REQUEST_TIMEOUT_SECONDS = 600


def _get(url: str, params: dict, timeout: int = REQUEST_TIMEOUT_SECONDS) -> requests.Response:
    return requests.get(url, params={**params, "serviceKey": SERVICE_KEY}, timeout=timeout)


def _parse(resp: requests.Response, item_tag: str) -> ET.Element | None:
    """item_tag가 있으면 성공으로 본다. 이 API들은 오류도 200으로 내려주기 때문이다."""
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return None
    return root if root.find(f".//{item_tag}") is not None else None


def _fetch(url: str, params: dict, item_tag: str, label: str, retries: int = 5) -> ET.Element:
    """일시적 오류(resultCode=99 등)는 간격을 늘려가며 재시도한다."""
    last = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(5 * attempt)
        try:
            resp = _get(url, params)
        except requests.RequestException as exc:
            last = f"요청 실패: {exc}"
            continue

        root = _parse(resp, item_tag)
        if root is not None:
            return root
        last = resp.text[:300]

    raise RuntimeError(f"{label} 응답 실패: {last}")


def _text(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    return el.text if el is not None else None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return _STYLE_JUNK.sub("", value).strip() or None


def _row(fields: list[str], **values) -> dict:
    row = dict.fromkeys(fields)
    row.update(values)
    return row


# ------------------------------------------------------------------- 자격증 목록

def fetch_certifications() -> list[dict]:
    rows: list[dict] = []

    root = _fetch(NATIONAL_QUAL_URL, {}, "item", "국가자격 종목 목록")
    for item in root.iter("item"):
        rows.append(_row(
            CERT_FIELDS,
            jm_cd=_text(item, "jmcd"),
            jm_nm=_text(item, "jmfldnm"),
            qual_gb_cd=_text(item, "qualgbcd"),
            series_nm=_text(item, "seriesnm"),
        ))

    for url, gb, label in (
        (WJM_URL, "W", "일학습병행제 정보 조회"),
        (CJM_URL, "C", "과정평가형자격 정보 조회"),
    ):
        page = 1
        collected = 0
        while True:
            root = _fetch(
                url,
                {"pageNo": page, "numOfRows": 100, "type": "xml"},
                "jmInfo",
                label,
            )
            items = list(root.iter("jmInfo"))
            for item in items:
                # W/C는 계열 구분이 없다. 일정도 자격구분 단위로만 나뉜다.
                rows.append(_row(
                    CERT_FIELDS,
                    jm_cd=_text(item, "jmCd"),
                    jm_nm=_text(item, "jmNm"),
                    qual_gb_cd=gb,
                    series_nm=None,
                ))
            collected += len(items)

            total_el = root.find(".//totalCount")
            total = int(total_el.text) if total_el is not None else collected
            if not items or collected >= total:
                break
            page += 1

    return rows


# ------------------------------------------------------------------- 상세 설명

def fetch_qual_details() -> list[dict]:
    rows: list[dict] = []
    for series_cd in SERIES_CODES:
        root = _fetch(
            QUAL_INFO_URL,
            {"seriesCd": series_cd},
            "item",
            f"국가기술자격 종목 정보(seriesCd={series_cd})",
        )
        for item in root.iter("item"):
            rows.append({
                "jm_cd": item.findtext("jmCd"),
                "mdoblig_fld_nm": _clean(item.findtext("mdobligFldNm")),
                "career": _clean(item.findtext("career")),
                "job": _clean(item.findtext("job")),
                "summary": _clean(item.findtext("summary")),
                "trend": _clean(item.findtext("trend")),
                "hist": _clean(item.findtext("hist")),
            })
    return rows


# ------------------------------------------------------------------- 시험일정

def _to_date(raw: str | None) -> date | None:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))


def _fetch_schedules_for(jm_cd: str, year: int, label: str) -> list[ET.Element]:
    items: list[ET.Element] = []
    page = 1
    while True:
        root = _fetch(
            EXAM_SCHD_URL,
            {
                "numOfRows": SCHEDULE_PAGE_SIZE,
                "pageNo": page,
                "dataFormat": "xml",
                "implYy": str(year),
                "jmCd": jm_cd,
            },
            "item",
            label,
        )
        page_items = list(root.iter("item"))
        items.extend(page_items)

        total_el = root.find(".//totalCount")
        total = int(total_el.text) if total_el is not None else len(items)
        if not page_items or len(items) >= total:
            break
        page += 1
    return items


def _checkpoint_path(year: int) -> str:
    return os.path.join(os.path.dirname(__file__), f".schedule_progress_{year}.txt")


def _load_checkpoint(year: int) -> set[str]:
    """이미 조회를 마친 종목코드. 일정이 0건이던 종목도 포함한다."""
    path = _checkpoint_path(year)
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def sync_exam_schedules(conn, year: int) -> int:
    """종목마다 시험일정을 조회해 저장한다.

    일정은 종목별로 다르다. 같은 '기사' 계열이라도 정보처리기사는 연 3회(6행),
    정밀화학기사는 1회(2행), 의공기사는 2회(4행)이고 아예 없는 종목도 많다.
    그래서 계열 단위로 묶지 못하고 종목 수만큼 호출해야 한다(수천 건, 수 시간).

    끊겨도 이어서 돌릴 수 있게 두 가지를 한다.
      - 한 종목 끝날 때마다 바로 커밋한다 (upsert 안에서 commit)
      - 조회를 마친 종목코드를 체크포인트 파일에 남겨 다시 부르지 않는다.
        일정이 0건이던 종목도 기록해야 재실행 때 또 조회하지 않는다.

    체크포인트는 "중단된 실행을 이어붙이는" 용도일 뿐이다. 한 번 끝까지 돌면 지워서,
    다음에 실행할 때는 처음부터 다시 받아 최신 일정으로 갱신되게 한다.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT jm_cd FROM certification ORDER BY jm_cd")
        jm_cds = [row["jm_cd"] for row in cursor.fetchall()]

    done = _load_checkpoint(year)
    if done:
        print(f"  이전 진행 기록 {len(done)}종목을 건너뛴다")

    key = ["jm_cd", "impl_yy", "impl_seq", "doc_reg_start_dt"]
    saved = 0
    failed = 0
    checkpoint = open(_checkpoint_path(year), "a", encoding="utf-8")

    try:
        for index, jm_cd in enumerate(jm_cds, start=1):
            if jm_cd in done:
                continue

            try:
                items = _fetch_schedules_for(jm_cd, year, f"시험일정({jm_cd})")
            except RuntimeError:
                # 실패한 종목은 체크포인트에 남기지 않는다. 다시 실행하면 재시도된다.
                failed += 1
                continue

            rows = [
                _row(
                    SCHEDULE_FIELDS,
                    jm_cd=jm_cd,
                    impl_yy=year,
                    impl_seq=_text(item, "implSeq") or "",
                    doc_reg_start_dt=_to_date(_text(item, "docRegStartDt")),
                    description=_text(item, "description"),
                    doc_reg_end_dt=_to_date(_text(item, "docRegEndDt")),
                    doc_exam_start_dt=_to_date(_text(item, "docExamStartDt")),
                    doc_exam_end_dt=_to_date(_text(item, "docExamEndDt")),
                    doc_pass_dt=_to_date(_text(item, "docPassDt")),
                    prac_reg_start_dt=_to_date(_text(item, "pracRegStartDt")),
                    prac_reg_end_dt=_to_date(_text(item, "pracRegEndDt")),
                    prac_exam_start_dt=_to_date(_text(item, "pracExamStartDt")),
                    prac_exam_end_dt=_to_date(_text(item, "pracExamEndDt")),
                    prac_pass_dt=_to_date(_text(item, "pracPassDt")),
                )
                for item in items
            ]
            saved += upsert(conn, "exam_schedule", SCHEDULE_FIELDS, rows, key)

            # DB 저장이 끝난 뒤에 기록해야, 저장 직전에 죽었을 때 이 종목을 다시 받는다.
            checkpoint.write(f"{jm_cd}\n")
            checkpoint.flush()

            if index % 100 == 0:
                print(f"  {index}/{len(jm_cds)} 종목 처리 | 저장 {saved}건 실패 {failed}건")
    finally:
        checkpoint.close()

    if failed:
        # 실패한 종목이 남아 있으면 체크포인트를 남겨둔다. 다시 실행하면 그것만 재시도한다.
        print(f"  조회 실패 {failed}종목 (다시 실행하면 실패분만 재시도된다)")
    else:
        # 끝까지 돌았으므로 기록을 지운다. 다음 실행은 처음부터 다시 받아 최신화한다.
        os.remove(_checkpoint_path(year))

    return saved


# ------------------------------------------------------------------------- DB

def connect():
    host = os.getenv("MYSQL_HOST")
    if not host:
        raise SystemExit("MYSQL_HOST가 .env에 설정되어 있지 않습니다.")
    return pymysql.connect(
        host=host,
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def create_tables(conn) -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        statements = [s.strip() for s in f.read().split(";") if s.strip()]
    with conn.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    conn.commit()


def upsert(conn, table: str, fields: list[str], rows: list[dict], key_fields: list[str]) -> int:
    if not rows:
        return 0
    columns = ", ".join(fields)
    placeholders = ", ".join(f"%({f})s" for f in fields)
    updates = ", ".join(f"{f} = VALUES({f})" for f in fields if f not in key_fields)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"

    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)
    conn.commit()
    return len(rows)


# ------------------------------------------------------------------------ main

def main() -> None:
    if not SERVICE_KEY:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")

    year = date.today().year

    conn = connect()
    try:
        create_tables(conn)

        print("자격증 목록 수집...")
        certs = fetch_certifications()
        print(f"  {upsert(conn, 'certification', CERT_FIELDS, certs, ['jm_cd'])}건 저장")

        print("상세 설명 수집...")
        details = fetch_qual_details()
        print(f"  {upsert(conn, 'qual_detail', DETAIL_FIELDS, details, ['jm_cd'])}건 저장")

        # 연말에는 다음 해 일정이 먼저 올라오므로 두 해를 함께 받는다.
        # 종목마다 호출해야 해서 가장 오래 걸리는 단계다.
        for target_year in (year, year + 1):
            print(f"{target_year}년 시험일정 수집... (종목마다 조회하므로 시간이 오래 걸린다)")
            print(f"  {sync_exam_schedules(conn, target_year)}건 저장")
    finally:
        conn.close()

    print("완료")


if __name__ == "__main__":
    main()
