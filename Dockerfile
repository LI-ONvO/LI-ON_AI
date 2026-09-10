# AI 서버 컨테이너.
# 백엔드·MySQL과 같은 docker-compose 안에서 나란히 돈다.
#
# 배치 스크립트(batch/)도 함께 담는다. 서버가 쓰지는 않지만, 자격증 데이터를 채울 때
# 컨테이너 안에서 실행하기 때문이다.
#   docker compose exec ai python -m batch.sync_certifications

FROM python:3.11-slim

# 파이썬이 .pyc를 남기지 않고, 로그를 버퍼링 없이 바로 내보내게 한다.
# 버퍼링을 두면 docker logs 에 출력이 뒤늦게 몰려서 장애를 늦게 알아차린다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성을 먼저 설치한다. 코드만 바뀌었을 때 이 층을 캐시에서 재사용해 빌드가 빨라진다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY batch/ ./batch/

# root로 돌리지 않는다. 컨테이너가 뚫려도 할 수 있는 일을 줄인다.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 설정이 완비됐는지까지 확인하는 /ready 를 쓴다. /health 는 프로세스가 살아있다는 뜻뿐이라
# DB 접속 정보가 빠진 채로도 통과한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
