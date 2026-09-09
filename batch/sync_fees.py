"""응시수수료만 수집한다.

종목마다 조회해야 하지만 한 번에 0.1초대라 613종목(국가기술·국가전문)이면 1분 남짓이다.
일학습병행·과정평가형은 검정형이 아니라 응시료가 없으므로 대상에서 뺀다.

실행:
    python -m batch.sync_fees

certification 테이블을 읽어 대상을 정하므로, 자격증 목록이 먼저 채워져 있어야 한다.
"""

from batch.sync_certifications import SERVICE_KEY, connect, create_tables, sync_exam_fees


def main() -> None:
    if not SERVICE_KEY:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY가 .env에 설정되어 있지 않습니다.")

    conn = connect()
    try:
        create_tables(conn)
        print("응시수수료 수집...")
        print(f"  {sync_exam_fees(conn)}건 저장")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
