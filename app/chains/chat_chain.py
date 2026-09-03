"""채팅 응답 생성 체인.

모델이 자격증 DB를 조회할 수 있도록 도구를 붙인다. 도구 없이 두면 모델이 학습 지식만으로
답해서, 폐지되었거나 존재하지 않는 자격증을 그럴듯하게 지어낸다.

도구 호출/결과 메시지는 이 요청 안에서만 쓰이고 백엔드로 넘어가지 않는다.
백엔드가 보관하는 대화 이력은 USER/AI 텍스트뿐이다.
"""

import json
from collections.abc import Sequence
from datetime import date

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.chains.base import build_messages, extract_text
from app.chains.tools import TOOL_SPECS, run_tool
from app.core.exceptions import LLMOutputError
from app.core.llm import get_chat_model, llm_call_guard
from app.core.logging import get_logger
from app.prompts import render_prompt
from app.repositories.certifications import get_certification
from app.schemas.chat import ChatMessage

logger = get_logger(__name__)

# 검색 -> 재검색이 끝없이 반복되지 않도록 상한을 둔다.
MAX_TOOL_ROUNDS = 4

# 기본값(0.3)에서는 도구를 건너뛰고 자기 지식으로 답해버리는 일이 있었다.
# 자격증 정보는 반드시 DB를 거쳐야 하므로 낮춰 잡는다.
CHAT_TEMPERATURE = 0.2


async def _selected_certification_note(jm_cd: str | None) -> str:
    """사용자가 고른 자격증을 시스템 프롬프트에 덧붙일 문구로 만든다.

    대화는 자격증을 하나 고른 뒤 시작하므로, 매번 검색으로 다시 찾게 하지 않고
    처음부터 대상을 알려준다.
    """
    if not jm_cd:
        return ""

    target = await get_certification(jm_cd)
    if target is None:
        logger.warning("종목코드 %s 를 찾지 못했습니다.", jm_cd)
        return ""

    lines = [
        "",
        "[사용자가 선택한 자격증]",
        f"- 종목명: {target['jmNm']} ({target['qualGbNm']}"
        + (f" / {target['seriesNm']}" if target["seriesNm"] else "")
        + ")",
        f"- 종목코드: {target['jmCd']}",
    ]
    for label, key in (("직종", "mdobligFldNm"), ("수행직무", "job"), ("개요", "summary")):
        if target.get(key):
            lines.append(f"- {label}: {target[key]}")

    lines.append(
        "대화는 이 자격증을 놓고 진행합니다. 사용자가 다른 자격증을 언급하지 않는 한 "
        "이 자격증을 기준으로 답하세요."
    )
    return "\n".join(lines)


async def run_chat_chain(
    history: Sequence[ChatMessage],
    content: str,
    jm_cd: str | None = None,
) -> str:
    """대화 맥락 + 신규 메시지로 AI 응답 텍스트를 만든다."""
    system_prompt = render_prompt("chat_system", today=date.today().isoformat())
    system_prompt += await _selected_certification_note(jm_cd)
    messages: list[BaseMessage] = build_messages(system_prompt, history, content)

    model = get_chat_model(temperature=CHAT_TEMPERATURE).bind_tools(TOOL_SPECS)

    for _ in range(MAX_TOOL_ROUNDS):
        async with llm_call_guard("chat"):
            result: AIMessage = await model.ainvoke(messages)

        if not result.tool_calls:
            text = extract_text(result.content)
            if not text:
                logger.warning("LLM이 빈 응답을 반환했습니다.")
                raise LLMOutputError("AI가 빈 응답을 반환했습니다.")
            return text

        # 도구 호출 메시지와 그 결과는 반드시 짝을 이뤄야 다음 호출이 받아들여진다.
        messages.append(result)
        for tool_call in result.tool_calls:
            output = await run_tool(tool_call["name"], _dump_args(tool_call["args"]))
            messages.append(ToolMessage(content=output, tool_call_id=tool_call["id"]))

    logger.warning("도구 호출이 %d회를 넘겨 응답을 만들지 못했습니다.", MAX_TOOL_ROUNDS)
    raise LLMOutputError("AI가 답변을 완성하지 못했습니다.")


def _dump_args(args: object) -> str:
    """LangChain은 도구 인자를 dict로 주고, run_tool은 JSON 문자열을 받는다."""
    if isinstance(args, str):
        return args
    return json.dumps(args, ensure_ascii=False)
