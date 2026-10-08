"""자격증 추천 체인.

대화가 없으므로 도구 호출 대신, 추천 가능한 자격증 목록(약 490건)을 통째로 프롬프트에 넣고
그중에서 고르게 한다. 목록이 작아 전부 들어가고, 이렇게 하면 모델이 DB에 없는 자격증을
지어낼 수 없다. 키워드 검색은 "보안"에 철도신호기사가 걸리는 식의 오매칭이 있어 쓰지 않는다.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.core.exceptions import LLMOutputError
from app.core.llm import get_chat_model, llm_call_guard
from app.core.logging import get_logger
from app.prompts import render_prompt
from app.repositories.certifications import list_recommendable_certifications
from app.schemas.recommend import RecommendUser
from langchain_core.messages import HumanMessage, SystemMessage

logger = get_logger(__name__)

# 추천은 사람마다 크게 달라지면 안 되므로 낮게 잡는다.
RECOMMEND_TEMPERATURE = 0.2


class RecommendationDraft(BaseModel):
    """모델이 채우는 추천 한 건."""

    jm_cd: str = Field(description="선택 가능한 자격증 목록에 있는 종목코드를 그대로 옮겨 적는다")
    reason: str = Field(description="이 자격증이 다루는 내용이 희망 분야와 어떻게 이어지는지 한두 문장")
    # 프롬프트로 "개수를 억지로 채우지 말라"고만 하면 무시하고 떡제조기능사까지 채워 넣는다.
    # 관련도를 스스로 표시하게 하고 "약함"은 서비스 계층에서 버린다.
    fit: Literal["직접", "기반", "약함"] = Field(
        default="직접",
        description="직접: 희망 분야의 핵심 업무를 다룬다. 기반: 직접은 아니지만 기초가 된다. 약함: 그 외",
    )


class RecommendationsDraft(BaseModel):
    """모델이 반환하는 추천 목록."""

    items: list[RecommendationDraft] = Field(description="관련도가 높은 순서로 정렬")


# 긴 것부터 비교해야 "산업기사"가 "기사"로 잡히지 않는다.
_GRADE_SUFFIXES = ("산업기사", "기능사", "기능장", "기술사", "기사")


def _grade(name: str, series: str | None) -> str:
    """종목명 끝에서 등급을 읽는다.

    seriesNm 은 계열이라 산업기사도 "기사"로 온다(정보처리산업기사 → 기사). 그대로 넘기면
    모델이 산업기사와 기사를 구분하지 못해 응시자격을 잘못 판단한다.
    "소방설비산업기사(기계분야)"처럼 괄호가 붙은 이름은 괄호 앞으로 판단한다.
    이름에 등급이 없으면(미용사(네일), 사회조사분석사2급) 계열을 쓰되, "기사" 계열은
    산업기사와 섞여 있어 기타로 둔다.
    """
    base = name.split("(")[0]
    for suffix in _GRADE_SUFFIXES:
        if base.endswith(suffix):
            return suffix
    if series in ("기능사", "기능장", "기술사"):
        return series
    return f"기타({series or '-'} 계열)"


def _format_candidates(candidates: list[dict]) -> str:
    lines = ["[선택 가능한 자격증 목록] 종목코드 | 종목명 | 등급 | 직종"]
    for c in candidates:
        field = c["mdobligFldNm"] or "-"
        lines.append(f"{c['jmCd']} | {c['jmNm']} | {_grade(c['jmNm'], c['seriesNm'])} | {field}")
    return "\n".join(lines)


def _format_user(user: RecommendUser, size: int) -> str:
    lines = ["[사용자 정보]"]
    if user.nickname:
        lines.append(f"- 호칭: {user.nickname}")
    if user.desired_fields:
        lines.append(f"- 희망 분야: {', '.join(user.desired_fields)}")
    for answer in user.onboarding:
        if answer.values:
            lines.append(f"- {answer.title}: {', '.join(answer.values)}")

    lines.append("")
    lines.append(
        f"위 사용자에게 맞는 자격증을 최대 {size}개 골라 주세요. "
        "관련이 약하면 개수를 채우지 말고 적게 골라도 됩니다."
    )
    return "\n".join(lines)


async def run_recommend_chain(
    user: RecommendUser, size: int
) -> tuple[list[RecommendationDraft], dict[str, str]]:
    """추천 초안과, 실제로 존재하는 종목코드 → 등급 매핑을 함께 반환한다.

    매핑은 서비스 계층이 모델 출력을 검증하고 응시자격 안내를 붙이는 데 쓴다.
    """
    candidates = await list_recommendable_certifications()
    if not candidates:
        raise LLMOutputError("추천할 수 있는 자격증 데이터가 없습니다. 배치를 먼저 실행하세요.")

    system_prompt = render_prompt("recommend_system", today=date.today().isoformat())
    messages = [
        SystemMessage(content=system_prompt),
        SystemMessage(content=_format_candidates(candidates)),
        HumanMessage(content=_format_user(user, size)),
    ]

    model = get_chat_model(temperature=RECOMMEND_TEMPERATURE).with_structured_output(
        RecommendationsDraft
    )

    async with llm_call_guard("recommend"):
        draft = await model.ainvoke(messages)

    if draft is None or not draft.items:
        logger.warning("추천 결과가 비어 있습니다.")
        raise LLMOutputError("AI가 추천 자격증을 생성하지 못했습니다.")

    return draft.items, {c["jmCd"]: _grade(c["jmNm"], c["seriesNm"]) for c in candidates}
