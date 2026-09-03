"""자격증 DB(MySQL) 접근.

배치가 채워둔 참조 데이터(자격증 목록·상세·시험일정)를 읽기만 한다. 쓰기는 하지 않는다.

PyMySQL은 동기 드라이버라 그대로 호출하면 이벤트 루프를 막는다.
쿼리는 짧으므로 asyncio.to_thread로 워커 스레드에 넘겨 처리한다.
"""

import asyncio
from collections.abc import Sequence
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import settings
from app.core.exceptions import AIServerError, ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def _connection():
    if not settings.mysql_host:
        raise ConfigurationError("자격증 DB 접속 정보(MYSQL_HOST)가 설정되지 않았습니다.")

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


def _fetch_all_sync(sql: str, args: Sequence) -> list[dict]:
    try:
        with _connection() as conn, conn.cursor() as cursor:
            cursor.execute(sql, args)
            return list(cursor.fetchall())
    except pymysql.MySQLError as exc:
        logger.exception("자격증 DB 조회 실패")
        raise AIServerError(f"자격증 DB 조회에 실패했습니다: {exc}") from exc


async def fetch_all(sql: str, args: Sequence = ()) -> list[dict]:
    """SELECT 결과를 dict 리스트로 반환한다."""
    return await asyncio.to_thread(_fetch_all_sync, sql, args)
