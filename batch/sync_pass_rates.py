"""합격률만 수집해 certification 의 doc_pass_rate / prac_pass_rate 를 갱신한다.

등급 단위로 조회하므로 한 해에 요청 7번이면 끝난다(시험일정처럼 종목마다 부르지 않는다).

종목마다 값 하나씩만 저장하므로, 최근 연도부터 내려오며 데이터가 있는 첫 해를 골라
그 해 전체 회차를 응시자수로 가중해 계산한다.

실행:
    python -m batch.sync_pass_rates       # 최근 5년까지 훑으며 최신값 사용
    python -m batch.sync_pass_rates 10    # 10년까지 거슬러 올라가며 찾기

데이터는 2008년부터 있다. 올해 것은 시험이 끝나야 올라오므로 연초에는 비어 있다.
"""

import sys

from batch.sync_certifications import (
    PASS_RATE_FIELDS,
    SERVICE_KEY,
    connect,
    create_tables,
    fetch_pass_rates,
    upsert,
)

# 최근 연도부터 몇 해까지 거슬러 올라가며 데이터를 찾을지.
# 폐지가 임박한 종목은 최근 몇 해 통계가 없기도 하다.
DEFAULT_YEARS_BACK = 5

KEY_FIELDS = ["jm_cd"]


def main() -> None:
    if not SERVICE_KEY:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")

    years_back = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_YEARS_BACK

    conn = connect()
    try:
        create_tables(conn)
        print(f"합격률 수집... (최근 {years_back}년까지 훑는다)")
        rows = fetch_pass_rates(years_back)
        saved = upsert(conn, "certification", PASS_RATE_FIELDS, rows, KEY_FIELDS)
        print(f"  {saved}종목 갱신")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
