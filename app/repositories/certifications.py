"""자격증 조회.

배치가 채워둔 세 테이블을 읽는다.
  certifications   전체 자격증 목록 (국가기술/국가전문/과정평가형/일학습병행)
  qual_details     국가기술자격 상세 설명 (진로·수행직무·개요·출제경향·변천과정)
  exam_schedules   회차별 시험일정

챗봇이 없는 자격증을 지어내지 않도록, 추천·설명은 반드시 여기를 거친다.
"""

from datetime import date

from app.core.config import settings
from app.core.db import fetch_all

# 같은 종목명이 자격구분만 다르게 존재한다(예: 프로그래밍기능사 = 국가기술자격/과정평가형자격).
# 시험 일정이 서로 다르므로 이름만으로 하나를 고르면 안 된다.
QUAL_GB_NAMES = {
    "T": "국가기술자격",
    "S": "국가전문자격",
    "W": "일학습병행자격",
    "C": "과정평가형자격",
}

# 검색어가 어디에 걸렸는지에 따라 가중치를 다르게 준다.
# 설명 본문(career/summary)은 길어서 "정보" 같은 흔한 단어가 무관한 종목에도 걸리기 때문이다.
_MATCH_FIELDS = [
    ("c.jm_nm", 100),          # 종목명
    ("d.mdoblig_fld_nm", 50),  # 직종
    ("d.hist", 30),            # 변천과정 - 폐지된 옛 종목명이 남아있다
    ("d.job", 10),             # 수행직무
    ("d.summary", 3),          # 개요
    ("d.career", 1),           # 진로
]


def _truncate(value: str | None) -> str | None:
    if not value:
        return None
    return value[: settings.max_field_chars]


def _build_search_sql(keywords: list[str], joiner: str) -> tuple[str, list[str]]:
    conditions = []
    scores = []
    args: list[str] = []
    score_args: list[str] = []

    for keyword in keywords:
        like = f"%{keyword}%"
        conditions.append("(" + " OR ".join(f"{col} LIKE %s" for col, _ in _MATCH_FIELDS) + ")")
        args.extend([like] * len(_MATCH_FIELDS))

        scores.append(
            " + ".join(
                f"(CASE WHEN {col} LIKE %s THEN {weight} ELSE 0 END)"
                for col, weight in _MATCH_FIELDS
            )
        )
        score_args.extend([like] * len(_MATCH_FIELDS))

    sql = f"""
        SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm,
               d.job, d.summary, d.career, d.hist,
               {" + ".join(scores)} AS score
        FROM qual_detail d
        JOIN certification c ON c.jm_cd = d.jm_cd
        WHERE {joiner.join(conditions)}
        ORDER BY score DESC, c.jm_nm
        LIMIT %s
    """
    return sql, [*score_args, *args]


async def search_certifications(keywords: list[str], limit: int | None = None) -> list[dict]:
    """키워드로 자격증을 찾는다. 상세 설명이 있는 국가기술자격이 대상이다.

    AND(모든 키워드가 걸린 것)를 먼저 시도한다. OR로만 하면 "정보처리 + 기능사" 검색에
    "기능사"만 걸린 도배기능사 같은 무관한 종목이 딸려온다. 다만 "요리 + 조리"처럼
    한 종목이 두 단어를 다 갖지 않는 경우 AND는 0건이 되므로 그때는 OR로 되돌린다.
    """
    if not keywords:
        return []

    limit = limit or settings.max_candidates

    rows: list[dict] = []
    for joiner in (" AND ", " OR "):
        sql, args = _build_search_sql(keywords, joiner)
        rows = await fetch_all(sql, [*args, limit])
        if rows:
            break

    return [
        {
            # 모델은 점수 계산을 모르므로 순위를 명시해 준다 (1이 가장 관련도 높음).
            "rank": index,
            "relevanceScore": int(row["score"]),
            "jmCd": row["jm_cd"],
            "jmNm": row["jm_nm"],
            "seriesNm": row["series_nm"],
            "mdobligFldNm": row["mdoblig_fld_nm"],
            "job": _truncate(row["job"]),
            "summary": _truncate(row["summary"]),
            "career": _truncate(row["career"]),
            "hist": _truncate(row["hist"]),
        }
        for index, row in enumerate(rows, start=1)
    ]


# 추천 대상 자격구분. 검정형 국가기술자격만 쓴다.
#   T 국가기술자격  - 원서접수만으로 응시 가능. 상세 설명도 있다.
#   C 과정평가형     - 지정 교육기관 과정을 이수해야 취득. T와 같은 이름이 많아 카드가 중복된다.
#   S 국가전문자격   - 공인노무사·관광통역안내사 등 성인 대상이 대부분.
#   W 일학습병행     - 기업에 학습근로자로 취업해야 응시 가능. 종목명도 "..._L2_ver1.0" 형태다.
RECOMMENDABLE_QUAL_GB_CDS = ("T",)


async def list_recommendable_certifications() -> list[dict]:
    """추천 후보가 될 자격증 목록(약 490건).

    목록이 작아 프롬프트에 전부 넣을 수 있고, 그러면 모델이 DB에 없는 자격증을 지어낼 수 없다.
    키워드 LIKE 검색은 "보안"에 철도신호기사가 걸리는 식의 오매칭이 있어 추천에는 쓰지 않는다.

    자격구분을 명시적으로 거른다. qual_details 조인만으로도 지금은 T만 남지만, 그건 배치가
    T의 설명만 수집하기 때문이라 다른 자격구분 설명이 채워지면 추천 대상이 조용히 늘어난다.
    """
    placeholders = ", ".join(["%s"] * len(RECOMMENDABLE_QUAL_GB_CDS))
    rows = await fetch_all(
        f"""
        SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm
        FROM qual_detail d
        JOIN certification c ON c.jm_cd = d.jm_cd
        WHERE c.qual_gb_cd IN ({placeholders})
        ORDER BY d.mdoblig_fld_nm, c.jm_nm
        """,
        list(RECOMMENDABLE_QUAL_GB_CDS),
    )
    return [
        {
            "jmCd": row["jm_cd"],
            "jmNm": row["jm_nm"],
            "seriesNm": row["series_nm"],
            "mdobligFldNm": row["mdoblig_fld_nm"],
        }
        for row in rows
    ]


async def get_certifications(jm_cds: list[str]) -> list[dict]:
    """여러 종목을 한 번에 조회한다. 추천 결과에 설명을 붙일 때 쓴다."""
    if not jm_cds:
        return []

    placeholders = ", ".join(["%s"] * len(jm_cds))
    rows = await fetch_all(
        f"""
        SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm, d.job, d.summary, d.career
        FROM certification c
        LEFT JOIN qual_detail d ON d.jm_cd = c.jm_cd
        WHERE c.jm_cd IN ({placeholders})
        """,
        jm_cds,
    )
    return [
        {
            "jmCd": row["jm_cd"],
            "jmNm": row["jm_nm"],
            "seriesNm": row["series_nm"],
            "mdobligFldNm": row["mdoblig_fld_nm"],
            "job": _truncate(row["job"]),
            "summary": _truncate(row["summary"]),
            "career": _truncate(row["career"]),
        }
        for row in rows
    ]


async def get_certification(jm_cd: str) -> dict | None:
    """사용자가 선택한 자격증 하나를 상세 설명까지 함께 가져온다.

    상세 설명은 국가기술자격에만 있으므로, 그 외 자격구분이면 이름·계열만 채워진다.
    """
    rows = await fetch_all(
        """
        SELECT c.jm_cd, c.jm_nm, c.qual_gb_cd, c.series_nm,
               d.mdoblig_fld_nm, d.job, d.summary, d.career
        FROM certification c
        LEFT JOIN qual_detail d ON d.jm_cd = c.jm_cd
        WHERE c.jm_cd = %s
        """,
        [jm_cd],
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "jmCd": row["jm_cd"],
        "jmNm": row["jm_nm"],
        "qualGbNm": QUAL_GB_NAMES.get(row["qual_gb_cd"], row["qual_gb_cd"]),
        "seriesNm": row["series_nm"],
        "mdobligFldNm": row["mdoblig_fld_nm"],
        "job": _truncate(row["job"]),
        "summary": _truncate(row["summary"]),
        "career": _truncate(row["career"]),
    }


async def resolve_certification(query: str, limit: int = 20) -> dict:
    """종목코드 또는 종목명으로 자격증을 찾는다. 전체 자격증이 대상이다.

    "기능사"처럼 넓은 검색어는 수백 건이 걸리므로 목록은 limit까지만 돌려주되,
    total에 실제 전체 개수를 담는다(잘린 목록을 전부라고 오해하지 않도록).
    """
    where = "WHERE jm_cd = %s OR jm_nm LIKE %s"
    args = [query, f"%{query}%"]

    counted = await fetch_all(f"SELECT COUNT(*) AS total FROM certification {where}", args)
    rows = await fetch_all(
        f"""
        SELECT jm_cd, jm_nm, qual_gb_cd FROM certification
        {where}
        ORDER BY CASE WHEN jm_nm = %s THEN 0 ELSE 1 END, jm_nm
        LIMIT %s
        """,
        [*args, query, limit],
    )

    return {
        "total": counted[0]["total"] if counted else 0,
        "matches": [
            {
                "jmCd": row["jm_cd"],
                "jmNm": row["jm_nm"],
                "qualGbNm": QUAL_GB_NAMES.get(row["qual_gb_cd"], row["qual_gb_cd"]),
            }
            for row in rows
        ],
    }


async def fetch_exam_schedules(jm_cd: str, year: int | None = None) -> list[dict]:
    """해당 종목의 시험일정을 회차 순으로 반환한다.

    일정은 종목마다 다르다(같은 '기사' 계열이라도 연 1~3회로 제각각이고, 아예 없는 종목도 있다).
    빈 목록은 "그 해 일정이 없음"을 뜻하며 오류가 아니다.

    데이터는 batch/sync_certifications.py 가 채운다. 이 서버는 읽기만 한다.
    """
    year = year or date.today().year
    rows = await fetch_all(
        """
        SELECT description, impl_seq,
               doc_reg_start_dt, doc_reg_end_dt,
               doc_exam_start_dt, doc_exam_end_dt, doc_pass_dt,
               prac_reg_start_dt, prac_reg_end_dt,
               prac_exam_start_dt, prac_exam_end_dt, prac_pass_dt
        FROM exam_schedule
        WHERE jm_cd = %s AND impl_yy = %s
        ORDER BY impl_seq, doc_reg_start_dt
        """,
        [jm_cd, year],
    )

    today = date.today()
    schedules = []
    for row in rows:
        events = []
        for start_col, end_col, label in (
            ("doc_reg_start_dt", "doc_reg_end_dt", "필기 원서접수"),
            ("doc_exam_start_dt", "doc_exam_end_dt", "필기 시험"),
            ("doc_pass_dt", None, "필기 합격발표"),
            ("prac_reg_start_dt", "prac_reg_end_dt", "실기 원서접수"),
            ("prac_exam_start_dt", "prac_exam_end_dt", "실기 시험"),
            ("prac_pass_dt", None, "실기 합격발표"),
        ):
            start = row.get(start_col)
            if not start:
                continue
            end = row.get(end_col) if end_col else None
            events.append({
                "label": label,
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "upcoming": (end or start) >= today,
            })

        schedules.append({
            "description": row["description"],
            "implSeq": row["impl_seq"],
            "events": events,
        })

    return schedules
