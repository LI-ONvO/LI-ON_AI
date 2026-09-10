"""챗봇이 쓰는 도구 정의와 실행.

자격증 설명을 전부 프롬프트에 넣을 수 없으므로, 모델이 필요할 때 DB를 조회하게 한다.
모델이 검색 여부와 검색어를 스스로 정하므로
  - 검색이 필요 없는 턴에는 조회하지 않고,
  - 결과가 신통치 않으면 다른 검색어로 다시 찾아볼 수 있다.
"""

import json
from datetime import date

from app.core.logging import get_logger
from app.repositories.certifications import (
    fetch_exam_fee,
    fetch_exam_schedules,
    fetch_pass_rate,
    resolve_certification,
    search_certifications,
)

logger = get_logger(__name__)

# 이름이 겹치는 종목은 이 개수까지 되묻지 않고 전부 조회해서 함께 보여준다.
# 모델에게 "각각 조회하라"고 맡기면 일부만 조회하고 나머지를 누락한다.
MAX_AUTO_FETCH = 3

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_certifications",
            "description": (
                "관심 분야·직무 키워드로 국가기술자격 종목을 검색한다. "
                "종목명, 직종, 수행직무, 개요, 진로, 변천과정을 대상으로 찾는다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "한국어 검색 키워드 2~5개 (예: ['요리', '조리'])",
                    }
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exam_schedule",
            "description": (
                "자격증의 시험일정(원서접수·필기·실기·합격발표)을 조회한다. "
                "국가기술자격뿐 아니라 국가전문자격·과정평가형·일학습병행 자격도 조회할 수 있다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "자격증 종목명 또는 종목코드 (예: '정보처리기사' 또는 '1320')",
                    },
                    "year": {"type": "integer", "description": "시행년도. 생략하면 올해."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pass_rate",
            "description": (
                "자격증의 최근 필기·실기 합격률(%)을 조회한다. "
                "난이도나 합격 가능성을 물을 때 쓴다. "
                "국가기술자격만 통계가 있고 국가전문자격·과정평가형에는 없다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "자격증 종목명 또는 종목코드 (예: '정보처리기사' 또는 '1320')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exam_fee",
            "description": (
                "자격증의 응시수수료(원)를 조회한다. 검정형인 국가기술자격·국가전문자격에만 있고 "
                "일학습병행·과정평가형에는 없다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "자격증 종목명 또는 종목코드 (예: '정보처리기사' 또는 '1320')",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


async def _search_tool(keywords: list[str]) -> dict:
    results = await search_certifications(keywords)
    payload: dict = {"count": len(results), "results": results}

    if results:
        payload["note"] = (
            "관련도 순으로 정렬돼 있습니다(rank 1이 가장 높음). "
            "rank가 낮고 relevanceScore 차이가 큰 항목은 검색어가 우연히 걸린 것일 수 있으니 "
            "무리해서 추천하지 마세요."
        )
    else:
        payload["note"] = (
            "검색 결과가 없습니다. 이 이름의 자격증은 존재하지 않거나 폐지되었을 수 있습니다. "
            "설명을 지어내지 말고 다른 검색어로 다시 찾아보세요."
        )
    return payload


async def _schedule_tool(query: str, year: int | None) -> dict:
    resolved = await resolve_certification(query)
    matches, total = resolved["matches"], resolved["total"]

    if not matches:
        return {"error": f"'{query}'에 해당하는 자격증을 찾지 못했습니다."}

    if total > MAX_AUTO_FETCH:
        shown = matches[:10]
        suffix = f" (아래는 그중 {len(shown)}개)" if total > len(shown) else ""
        return {
            "ambiguous": True,
            "total": total,
            "note": (
                f"'{query}'로 검색된 자격증이 {total}개입니다{suffix}. "
                "사용자에게 어느 것인지 되물어보세요."
            ),
            "candidates": shown,
        }

    results = []
    for target in matches:
        entry = dict(target)
        entry["schedules"] = await fetch_exam_schedules(target["jmCd"], year)
        if not entry["schedules"]:
            entry["note"] = "해당 연도의 시험일정이 아직 등록되지 않았습니다."
        results.append(entry)

    payload: dict = {"today": date.today().isoformat(), "results": results}
    if len(results) > 1:
        payload["note"] = (
            "같은 이름의 자격증이 자격구분별로 여러 개 있습니다. "
            "일정이 서로 다르므로 qualGbNm으로 구분해 모두 안내하세요."
        )
    return payload


async def _pass_rate_tool(query: str) -> dict:
    """일정 도구와 같은 방식으로 종목을 특정한 뒤 합격률을 붙인다."""
    resolved = await resolve_certification(query)
    matches, total = resolved["matches"], resolved["total"]

    if not matches:
        return {"error": f"'{query}'에 해당하는 자격증을 찾지 못했습니다."}

    if total > MAX_AUTO_FETCH:
        return {
            "ambiguous": True,
            "total": total,
            "note": (
                f"'{query}'로 검색된 자격증이 {total}개입니다. "
                "사용자에게 어느 것인지 되물어보세요."
            ),
            "candidates": matches[:10],
        }

    results = []
    for target in matches:
        entry = dict(target)
        rate = await fetch_pass_rate(target["jmCd"])
        if rate:
            entry["passRates"] = rate["passRates"]
        else:
            entry["note"] = "이 자격증은 합격률 통계가 공개되지 않았습니다."
        results.append(entry)

    return {
        "results": results,
        "note": (
            "passRate는 가장 최근 연도의 전체 회차를 응시자수로 가중해 계산한 값입니다(단위 %). "
            "특정 회차의 값이 아니고 연도별 추이도 제공하지 않으니, 몇 년도 수치냐고 물으면 "
            "최근 자료라고만 답하세요. "
            "합격률이 낮다고 무조건 응시를 말리지 말고, 난이도 참고로만 설명하세요."
        ),
    }


async def _fee_tool(query: str) -> dict:
    resolved = await resolve_certification(query)
    matches, total = resolved["matches"], resolved["total"]

    if not matches:
        return {"error": f"'{query}'에 해당하는 자격증을 찾지 못했습니다."}

    if total > MAX_AUTO_FETCH:
        return {
            "ambiguous": True,
            "total": total,
            "note": (
                f"'{query}'로 검색된 자격증이 {total}개입니다. "
                "사용자에게 어느 것인지 되물어보세요."
            ),
            "candidates": matches[:10],
        }

    results = []
    for target in matches:
        entry = dict(target)
        fee = await fetch_exam_fee(target["jmCd"])
        if fee:
            entry["fee"] = fee["fees"]
        else:
            entry["note"] = "이 자격증은 응시수수료 정보가 없습니다."
        results.append(entry)

    return {
        "results": results,
        "note": "금액 단위는 원입니다. 수수료는 바뀔 수 있으니 최종 금액은 큐넷 확인을 권하세요.",
    }


async def run_tool(name: str, arguments: str) -> str:
    """모델이 요청한 도구를 실행하고 결과를 JSON 문자열로 돌려준다."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "인자를 JSON으로 읽을 수 없습니다."}, ensure_ascii=False)

    logger.info("도구 호출 | name=%s args=%s", name, args)

    if name == "search_certifications":
        payload = await _search_tool(args.get("keywords", []))
    elif name == "get_exam_schedule":
        payload = await _schedule_tool(args.get("query", ""), args.get("year"))
    elif name == "get_pass_rate":
        payload = await _pass_rate_tool(args.get("query", ""))
    elif name == "get_exam_fee":
        payload = await _fee_tool(args.get("query", ""))
    else:
        payload = {"error": f"알 수 없는 도구: {name}"}

    return json.dumps(payload, ensure_ascii=False, default=str)
