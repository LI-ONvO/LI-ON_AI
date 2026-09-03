"""스키마 공통 베이스.

백엔드(Spring)는 camelCase JSON을 주고받는다. 파이썬 코드는 snake_case를 쓰므로
alias_generator로 두 표기를 이어준다.

  파이썬 필드      JSON 키
  session_id   ↔  sessionId
  order_no     ↔  orderNo
  target_date  ↔  targetDate

populate_by_name=True 라서 snake_case로 들어오는 요청도 함께 받아준다(테스트/수동 호출 편의).
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
