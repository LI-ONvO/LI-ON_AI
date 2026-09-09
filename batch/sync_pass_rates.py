"""합격률만 수집한다.

등급 단위로 조회하므로 한 해에 요청 7번이면 끝난다(시험일정처럼 종목마다 부르지 않는다).
연도 하나에 3천 건 안팎, 몇 초면 받는다.

실행:
    python -m batch.sync_pass_rates          # 최근 5년
    python -m batch.sync_pass_rates 2020     # 2020년만
    python -m batch.sync_pass_rates 2015 2025  # 범위

데이터는 2008년부터 있다. 올해 것은 시험이 끝나야 올라오므로 연초에는 비어 있다.
"""

import sys
from datetime import date

from batch.sync_certifications import (
    PASS_RATE_FIELDS,
    SERVICE_KEY,
    connect,
    create_tables,
    fetch_pass_rates,
    upsert,
)

# 챗봇이 "요즘 합격률"을 말할 때 쓸 만큼만 기본으로 받는다. 더 필요하면 인자로 범위를 준다.
DEFAULT_YEARS = 5

KEY_FIELDS = ["jm_cd", "impl_yy", "impl_seq", "exam_typ"]


def _target_years() -> list[int]:
    if len(sys.argv) > 2:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        return list(range(start, end + 1))
    if len(sys.argv) > 1:
        return [int(sys.argv[1])]
    this_year = date.today().year
    return list(range(this_year - DEFAULT_YEARS + 1, this_year + 1))


def main() -> None:
    if not SERVICE_KEY:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")

    conn = connect()
    try:
        create_tables(conn)
        total = 0
        for year in _target_years():
            rows = fetch_pass_rates(year)
            saved = upsert(conn, "pass_rate", PASS_RATE_FIELDS, rows, KEY_FIELDS)
            total += saved
            print(f"  {year}년 {saved}건")
        print(f"합계 {total}건 저장")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
