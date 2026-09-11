"""자격증 DB 접속 확인 스크립트.

.env 의 MYSQL_* 값으로 접속해서 무엇이 잘못됐는지 알려준다.
데이터를 넣거나 고치지 않고 읽기만 한다.

실행:
    python -m batch.check_db
"""

import os
import socket

import pymysql
from dotenv import load_dotenv

load_dotenv()

TABLES = ("certification", "qual_detail", "exam_schedule")


def main() -> None:
    host = os.getenv("MYSQL_HOST", "")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DB", "")

    if not host:
        print("[X] .env 에 MYSQL_HOST 가 없습니다.")
        return

    print(f"대상: {user}@{host}:{port}/{database}\n")

    # 1단계: 포트가 열려 있는지 (MySQL 로그인과는 별개)
    sock = socket.socket()
    sock.settimeout(5)
    try:
        sock.connect((host, port))
        print("[O] 포트 연결 성공")
    except Exception as exc:
        print(f"[X] 포트 연결 실패: {exc}")
        print("    - 주소와 포트가 맞는지 확인하세요.")
        print("    - 접속 허용 IP 목록에 내 IP 가 있어야 합니다. 관리형 DB 는 기본으로 막아둡니다.")
        print("    - MySQL 이 bind-address=127.0.0.1 로 묶여 있으면 외부에서 못 붙습니다.")
        return
    finally:
        sock.close()

    # 2단계: 실제 로그인
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password, database=database,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, connect_timeout=8,
        )
    except pymysql.err.OperationalError as exc:
        code = exc.args[0]
        print(f"[X] 로그인 실패: {exc}")
        if code == 1130:
            print("    이 IP 에서 접속할 수 있는 계정이 없지롱병신.")
            print("    MySQL 은 계정을 '아이디 + 접속 위치' 한 쌍으로 구분합니다.")
            print("    서버에서 아래를 실행해 달라고 요청하세요.")
            print("    ('%' 는 아무 곳에서나 접속을 허용한다는 뜻입니다. 접속 위치가 정해져 있으면")
            print("     그 주소로 좁히는 편이 안전합니다.)")
            print(f"      CREATE USER '{user}'@'%' IDENTIFIED BY '<비밀번호>';")
            print(f"      GRANT ALL PRIVILEGES ON {database}.* TO '{user}'@'%';")
            print("      FLUSH PRIVILEGES;")
        elif code == 1045:
            print("    아이디 또는 비밀번호가 틀렸지롱병신. .env 값을 확인하세요.")
        elif code == 1049:
            print(f"    '{database}' 데이터베이스가 없지롱병신. 서버에서 먼저 만들어야 합니다.")
        return

    # 3단계: 테이블과 데이터
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS v, CURRENT_USER() AS u")
            info = cursor.fetchone()
            print(f"[O] 로그인 성공 (MySQL {info['v']}, 계정 {info['u']})\n")

            cursor.execute("SHOW TABLES")
            existing = {list(row.values())[0] for row in cursor.fetchall()}

            for table in TABLES:
                if table not in existing:
                    print(f"[ ] {table}: 테이블 없음 (batch.sync_certifications 실행 시 생성됨)")
                    continue
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                print(f"[O] {table}: {cursor.fetchone()['n']}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
