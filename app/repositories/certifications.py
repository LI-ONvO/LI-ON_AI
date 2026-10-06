"""자격증 조회.

자격증 DB 는 백엔드 서버 안쪽에 있어 직접 읽지 않고 백엔드 API 로 조회한다(app/core/backend.py).
명세는 docs/BACKEND_API.md. 데이터를 채우는 배치는 batch/ 에서 DB 에 직접 쓴다.

챗봇이 없는 자격증을 지어내지 않도록, 추천·설명은 반드시 여기를 거친다.

백엔드는 DB 행에 가까운 형태로 주고, 모델에게 보여줄 모양(순위, 일정 라벨, 지난 일정 표시)은
여기서 만든다. 그래야 백엔드와 가공 로직이 갈라지지 않는다.
"""

import time
from datetime import date

from app.core.backend import get_json
from app.core.config import settings

# 같은 종목명이 자격구분만 다르게 존재한다(예: 프로그래밍기능사 = 국가기술자격/과정평가형자격).
# 시험 일정이 서로 다르므로 이름만으로 하나를 고르면 안 된다.
QUAL_GB_NAMES = {
    "T": "국가기술자격",
    "S": "국가전문자격",
    "W": "일학습병행자격",
    "C": "과정평가형자격",
}

# 백엔드 검색 API 가 받는 키워드 최대 개수. 넘기면 422 로 거절된다.
MAX_SEARCH_KEYWORDS = 5


def _truncate(value: str | None) -> str | None:
    if not value:
        return None
    return value[: settings.max_field_chars]


def _qual_gb_name(code: str | None) -> str | None:
    return QUAL_GB_NAMES.get(code, code) if code else None


# --------------------------------------------------------------------------- 상세

# 같은 요청 안에서 상세를 여러 번 부른다. 로드맵은 종목 정보 1번 + 올해·내년 일정 2번으로
# 같은 종목 상세를 세 번 가져온다. 상세 응답에 일정·응시료·합격률이 다 들어 있으므로 잠깐 보관한다.
# 서버리스라 인스턴스가 살아 있는 동안만 유지되고, 배치가 하루 한 번 갱신하는 데이터라 짧게 둔다.
_DETAIL_TTL_SECONDS = 60
_detail_cache: dict[str, tuple[float, dict | None]] = {}


async def _get_detail(jm_cd: str) -> dict | None:
    """GET /api/certificates/{jmCd}. 없는 종목이면 None."""
    now = time.monotonic()
    cached = _detail_cache.get(jm_cd)
    if cached and now - cached[0] < _DETAIL_TTL_SECONDS:
        return cached[1]

    detail = await get_json(f"/api/certificates/{jm_cd}")
    _detail_cache[jm_cd] = (now, detail)
    return detail


async def get_certification(jm_cd: str) -> dict | None:
    """사용자가 선택한 자격증 하나를 상세 설명까지 함께 가져온다.

    상세 설명은 국가기술자격에만 있으므로, 그 외 자격구분이면 이름·계열만 채워진다.
    """
    detail = await _get_detail(jm_cd)
    if detail is None:
        return None

    return {
        "jmCd": detail.get("jmCd"),
        "jmNm": detail.get("name"),
        "qualGbNm": _qual_gb_name(detail.get("qualGbCd")),
        "seriesNm": detail.get("seriesNm"),
        "mdobligFldNm": detail.get("mdobligFldNm"),
        "job": _truncate(detail.get("job")),
        # 백엔드 명세상 description 이 qual_detail.summary 다.
        "summary": _truncate(detail.get("description")),
        "career": _truncate(detail.get("career")),
    }


# --------------------------------------------------------------------------- 검색

async def search_certifications(keywords: list[str], limit: int | None = None) -> list[dict]:
    """키워드로 자격증을 찾는다. 상세 설명이 있는 국가기술자격이 대상이다.

    가중치 검색(종목명 100 · 직종 50 · 변천과정 30 · 수행직무 10 · 개요 3 · 진로 1)과
    "AND 먼저, 0건이면 OR" 규칙은 백엔드가 수행한다.
    """
    cleaned = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    if not cleaned:
        return []

    body = await get_json(
        "/api/certificates/search",
        {
            "keywords": ",".join(cleaned[:MAX_SEARCH_KEYWORDS]),
            "size": limit or settings.max_candidates,
        },
    )
    rows = (body or {}).get("content", [])

    return [
        {
            # 모델은 점수 계산을 모르므로 순위를 명시해 준다 (1이 가장 관련도 높음).
            "rank": index,
            "relevanceScore": int(row.get("score") or 0),
            "jmCd": row.get("jmCd"),
            "jmNm": row.get("name"),
            "seriesNm": row.get("seriesNm"),
            "mdobligFldNm": row.get("mdobligFldNm"),
            "job": _truncate(row.get("job")),
            "summary": _truncate(row.get("summary")),
            "career": _truncate(row.get("career")),
            "hist": _truncate(row.get("hist")),
        }
        for index, row in enumerate(rows, start=1)
    ]


async def list_recommendable_certifications() -> list[dict]:
    """추천 후보가 될 자격증 목록(약 490건).

    목록이 작아 프롬프트에 전부 넣을 수 있고, 그러면 모델이 DB에 없는 자격증을 지어낼 수 없다.
    국가기술자격(T) 중 상세 설명이 있는 종목만 백엔드가 골라 준다.
    """
    body = await get_json("/api/certificates/recommendable")
    return [
        {
            "jmCd": row.get("jmCd"),
            "jmNm": row.get("name"),
            "seriesNm": row.get("seriesNm"),
            "mdobligFldNm": row.get("mdobligFldNm"),
        }
        for row in (body or {}).get("content", [])
    ]


async def resolve_certification(query: str, limit: int = 20) -> dict:
    """종목코드 또는 종목명으로 자격증을 찾는다. 전체 자격증이 대상이다.

    "기능사"처럼 넓은 검색어는 수백 건이 걸리므로 목록은 limit까지만 돌려주되,
    total에 실제 전체 개수를 담는다(잘린 목록을 전부라고 오해하지 않도록).
    """
    query = query.strip()
    if not query:
        return {"total": 0, "matches": []}

    body = await get_json("/api/certificates/resolve", {"query": query, "size": limit}) or {}
    return {
        "total": body.get("totalElements", 0),
        "matches": [
            {
                "jmCd": row.get("jmCd"),
                "jmNm": row.get("name"),
                "qualGbNm": _qual_gb_name(row.get("qualGbCd")),
            }
            for row in body.get("content", [])
        ],
    }


# --------------------------------------------------------------------------- 일정

def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _seq_number(value: str | None) -> int:
    """회차 "01" 과 "1" 을 같은 값으로 정렬하기 위해 숫자로 바꾼다."""
    try:
        return int(value or 0)
    except ValueError:
        return 0


_EVENT_FIELDS = (
    ("docRegStartDt", "docRegEndDt", "필기 원서접수"),
    ("docExamStartDt", "docExamEndDt", "필기 시험"),
    ("docPassDt", None, "필기 합격발표"),
    ("pracRegStartDt", "pracRegEndDt", "실기 원서접수"),
    ("pracExamStartDt", "pracExamEndDt", "실기 시험"),
    ("pracPassDt", None, "실기 합격발표"),
)


async def fetch_exam_schedules(jm_cd: str, year: int | None = None) -> list[dict]:
    """해당 종목의 시험일정을 회차 순으로 반환한다.

    일정은 종목마다 다르다(같은 '기사' 계열이라도 연 1~3회로 제각각이고, 아예 없는 종목도 있다).
    빈 목록은 "그 해 일정이 없음"을 뜻하며 오류가 아니다.

    백엔드 상세 응답에 모든 연도 일정이 함께 오므로 여기서 연도를 거른다.
    """
    year = year or date.today().year
    detail = await _get_detail(jm_cd)
    if detail is None:
        return []

    rows = [s for s in detail.get("examSchedules") or [] if s.get("implYy") == year]
    rows.sort(key=lambda s: (_seq_number(s.get("implSeq")), s.get("docRegStartDt") or ""))

    today = date.today()
    schedules = []
    for row in rows:
        events = []
        for start_key, end_key, label in _EVENT_FIELDS:
            start = _to_date(row.get(start_key))
            if not start:
                continue
            end = _to_date(row.get(end_key)) if end_key else None
            events.append({
                "label": label,
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "upcoming": (end or start) >= today,
            })

        seq = _seq_number(row.get("implSeq"))
        schedules.append({
            # 백엔드 일정에는 회차 설명 문구가 없어 만든다. 로드맵이 올해·내년 일정을 함께 보므로
            # 연도가 드러나야 모델이 헷갈리지 않는다.
            "description": f"{year}년도 제{seq}회" if seq else f"{year}년도",
            "implSeq": row.get("implSeq"),
            "events": events,
        })

    return schedules


# ----------------------------------------------------------------- 합격률·응시료

async def fetch_pass_rate(jm_cd: str) -> dict | None:
    """필기·실기 합격률(%)을 반환한다. 없으면 None.

    배치가 저장해 둔 값은 최근 자료 기준 하나다. 연도별 추이는 담고 있지 않다.
    국가기술자격에만 통계가 있어 그 외 자격구분은 대개 null 이다.
    """
    detail = await _get_detail(jm_cd)
    if detail is None:
        return None

    rates = [
        {"examType": label, "passRate": float(detail[key])}
        for key, label in (("docPassRate", "필기"), ("pracPassRate", "실기"))
        if detail.get(key) is not None
    ]
    return {"passRates": rates} if rates else None


async def fetch_exam_fee(jm_cd: str) -> dict | None:
    """응시수수료(원)를 반환한다. 없으면 None.

    검정형(국가기술·국가전문)에만 있다. 일학습병행·과정평가형은 응시료 개념이 없어
    None이 정상이다.
    """
    detail = await _get_detail(jm_cd)
    if detail is None:
        return None

    fees = [
        {"examType": label, "won": detail[key]}
        for key, label in (("docFee", "필기"), ("pracFee", "실기"))
        if detail.get(key) is not None
    ]
    return {"fees": fees} if fees else None
