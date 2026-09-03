"""로깅 설정.

uvicorn이 자체 핸들러를 붙이기 때문에 루트 로거에 핸들러가 이미 있으면 중복 출력이 되지 않도록
한 번만 설정한다.
"""

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # 요청마다 찍히는 uvicorn 액세스 로그는 자체 미들웨어 로그와 중복이라 한 단계 낮춘다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
