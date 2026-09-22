"""시험일정만 수집한다.

일정은 종목마다 API를 불러야 해서 오래 걸린다(수천 종목, 수 시간).
목록·상세는 이미 채워져 있고 일정만 다시 받고 싶을 때 쓴다.

실행:
    python -m batch.sync_schedules          # 올해 + 내년
    python -m batch.sync_schedules 2026     # 특정 연도만

공공데이터포털 개발계정 키는 이 API를 하루 1,000번까지만 부를 수 있다. 한도를 넘기면
그 자리에서 멈추고, 다음 날 같은 명령을 실행하면 이어서 받는다.

중간에 끊어도 된다. 한 종목 끝날 때마다 저장하고 진행 기록을 남기므로,
다시 실행하면 이미 받은 종목은 건너뛰고 이어서 받는다.
끝까지 완주하면 기록을 지워서 다음 실행 때는 처음부터 다시 받아 최신화한다.
"""

import sys
from datetime import date

from batch.sync_certifications import (
    SERVICE_KEY,
    DailyQuotaExceeded,
    connect,
    create_tables,
    sync_exam_schedules,
)


def main() -> None:
    if not SERVICE_KEY:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")

    if len(sys.argv) > 1:
        years = [int(sys.argv[1])]
    else:
        # 연말에는 다음 해 일정이 먼저 올라오므로 두 해를 함께 받는다.
        years = [date.today().year, date.today().year + 1]

    conn = connect()
    try:
        create_tables(conn)
        for year in years:
            print(f"{year}년 시험일정 수집... (종목마다 조회하므로 오래 걸린다)")
            print(f"  {sync_exam_schedules(conn, year)}건 저장")
    except DailyQuotaExceeded:
        # 개발계정 키는 시험일정 API가 하루 1,000번까지다. 받은 건 저장됐고 진행 기록도 남아 있다.
        raise SystemExit("오늘 호출 한도를 다 썼습니다. 내일 같은 명령으로 이어서 받으세요.") from None
    finally:
        conn.close()

    print("완료")


if __name__ == "__main__":
    main()
