# LI-ON_AI

대덕소프트웨어마이스터고등학교의 자격증 AI 학습 계획 제공 서비스, AI 서버입니다.

백엔드가 사용자 요청을 처리하는 도중 프록시로 호출하는 **상태 없는(stateless)** 서버입니다.
대화 이력은 백엔드가 DB에 보관하고, 이 서버는 매 요청마다 전달받은 맥락으로만 응답을 만듭니다.

```
클라이언트 ──▶ 백엔드 ──▶ AI 서버(이 저장소) ──▶ OpenAI
                 │            │
                 │            └──▶ 자격증 DB (MySQL, 읽기 전용)
                 └── 메시지/로드맵 영속화
```

자격증 목록·상세·시험일정은 `batch/sync_certifications.py` 가 공공데이터포털에서 받아 MySQL에
채워 둔다. AI 서버는 이 테이블을 **읽기만** 한다. 모델이 DB에 없는 자격증을 지어내지 않도록,
추천·설명·일정 안내는 모두 이 데이터를 거친다.

## 요구 사항

- Python 3.10 이상 (3.11+ 권장)
- OpenAI API 키
- MySQL (자격증 데이터 보관)
- 공공데이터포털 서비스키 (자격증 데이터 수집용)

## 시작하기

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
# .env 를 열어 OPENAI_API_KEY 를 채웁니다.

python -m batch.sync_certifications   # 자격증 데이터를 MySQL에 채운다 (최초 1회, 갱신 시 재실행)

uvicorn app.main:app --reload
```

`sync_certifications`는 자격증 목록(약 3,700종목), 국가기술자격 상세 설명(약 490종목),
올해·내년 시험일정을 받아 온다.

시험일정은 종목마다 다르므로(같은 '기사' 계열이라도 연 1~3회로 제각각이고 아예 없는 종목도 많다)
종목 수만큼 API를 호출해야 한다. **첫 실행은 수 시간 걸린다.** 중간에 끊겨도 한 종목씩 바로
저장하고 진행 기록(`batch/.schedule_progress_{연도}.txt`)을 남기므로, 다시 실행하면 이어서 받는다.
끝까지 돌면 그 기록을 지워서 다음 실행 때는 처음부터 다시 받아 최신화한다.

서버가 뜨면 <http://127.0.0.1:8000/docs> 에서 Swagger UI로 직접 호출해 볼 수 있습니다.

## 테스트

```bash
pytest
```

테스트는 LLM을 모킹하므로 API 키나 네트워크 없이 전부 통과합니다.

## API

모든 요청/응답 JSON은 백엔드와 맞추기 위해 **camelCase**를 씁니다.

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/health` | 프로세스 생존 확인 (LLM 호출 없음) |
| GET | `/ready` | 설정 완비 여부 확인 |
| POST | `/v1/chat` | 대화 맥락 기반 AI 응답 생성 |
| POST | `/v1/roadmap` | 대화 맥락 기반 구조화 로드맵 생성 |
| POST | `/v1/recommend` | 사용자 프로필 기반 자격증 추천 (대화 없음) |

### POST /v1/chat

백엔드의 `POST /api/chat/sessions/{sessionId}/messages` 에 대응합니다.

```jsonc
// 요청
{
  "sessionId": 1,
  "jmCd": "1320",
  "history": [
    { "sender": "USER", "content": "정보처리기사 준비하려고 해" },
    { "sender": "AI",   "content": "언제까지 취득하는 게 목표인가요?" }
  ],
  "content": "3개월 안에 따기 가능해?"
}

// 응답 200
{
  "content": "주당 15시간 정도 확보되면 3개월 안에 가능합니다. ..."
}
```

`jmCd` 는 사용자가 대화를 시작하기 전에 고른 자격증입니다. 값이 있으면 그 자격증의 이름·직무·개요를
시스템 프롬프트에 넣어, 매번 검색으로 다시 찾지 않고 처음부터 대상을 알고 답하게 합니다.
생략하면 AI가 대화 내용에 따라 도구로 검색합니다.

`history` 는 오래된 메시지가 앞에 오도록 정렬해서 보냅니다. 서버는 최근
`MAX_HISTORY_MESSAGES` 개만 모델에 전달합니다.

### POST /v1/roadmap

백엔드의 `POST /api/chat/sessions/{sessionId}/roadmaps` 에 대응합니다.

```jsonc
// 요청 (jmCd 는 필수, title 은 선택. title 이 없으면 AI가 생성)
{
  "sessionId": 1,
  "jmCd": "1320",
  "history": [ /* ... */ ],
  "title": "3개월 속성 플랜"
}

// 응답 200
{
  "title": "3개월 속성 플랜",
  "steps": [
    {
      "title": "필기 이론 1회독",
      "description": "5과목 개념 정리, 과목당 3일",
      "orderNo": 1,
      "targetDate": "2026-08-15"
    },
    {
      "title": "기출 5개년 풀이",
      "description": "회차당 1일, 오답노트 작성",
      "orderNo": 2,
      "targetDate": "2026-09-01"
    }
  ]
}
```

응답에 `id` 는 없습니다. 스텝 ID는 백엔드가 영속화하면서 부여합니다.

`jmCd` 는 사용자가 고른 자격증입니다. 로드맵은 항상 이 자격증 하나를 대상으로 만듭니다.
서버는 이 종목의 **실제 시험일정을 DB에서 읽어** 프롬프트에 넣으므로, `targetDate` 가 원서접수
마감일이나 시험일을 기준으로 역산됩니다. 이 값이 없으면 모델이 대화의 "3개월 남았다" 같은 말만
보고 날짜를 지어냅니다.

`orderNo` 는 항상 1부터 1씩 증가하도록 서버에서 다시 매깁니다. `targetDate` 는 오늘 이후
날짜만 남기고, 앞 스텝보다 이른 날짜는 `null` 로 정리합니다.

### POST /v1/recommend

메인 페이지에서 추천 자격증 카드를 띄울 때 씁니다. 대화 없이 사용자 프로필만 받습니다.

```jsonc
// 요청
{
  "userId": 1,
  "size": 5,
  "user": {
    "nickname": "시흔",
    "desiredFields": ["클라우드", "보안"],
    "onboarding": [
      { "key": "study_time", "title": "하루 학습 가능 시간", "values": ["1~2시간"] }
    ]
  }
}

// 응답 200
{
  "items": [
    { "jmCd": "1320", "reason": "정보처리기사는 클라우드와 보안 시스템을 이해하는 데 필요한 기초 지식을 다룹니다." }
  ]
}
```

추천 후보는 상세 설명이 있는 국가기술자격 약 490종목입니다. 이 목록을 통째로 프롬프트에 넣고
그중에서 고르게 하므로, 모델이 존재하지 않는 자격증을 지어낼 수 없습니다. 키워드 LIKE 검색은
"보안"에 철도신호기사가 걸리는 식의 오매칭이 있어 추천에는 쓰지 않습니다.

그래도 모델이 목록에 없는 코드를 적어낼 수 있으므로, 서비스 계층에서 **존재하지 않는 종목코드와
중복을 걸러냅니다.** 희망 분야에 맞는 자격증이 부족하면 `items`가 `size`보다 적을 수 있습니다.

### 오류 응답

모든 오류는 형태가 같습니다.

```json
{ "code": "LLM_TIMEOUT", "message": "AI 모델 응답이 지연되어 요청을 완료하지 못했습니다.", "detail": null }
```

| Status | code | 발생 상황 | 백엔드 권장 처리 |
| --- | --- | --- | --- |
| 422 | `INVALID_REQUEST` | 요청 형식 오류 | 400 반환 (백엔드 버그) |
| 502 | `LLM_UPSTREAM_ERROR` | LLM 호출 실패 (인증·레이트리밋·네트워크) | 502 반환 |
| 502 | `LLM_OUTPUT_INVALID` | LLM이 형식에 맞지 않는 응답 반환 | 502 반환 |
| 504 | `LLM_TIMEOUT` | LLM 응답 지연 | 504 반환 |
| 500 | `AI_INTERNAL_ERROR` | 그 외 예기치 못한 오류 | 502 반환 |

백엔드는 AI 서버 호출 타임아웃을 `REQUEST_TIMEOUT_SECONDS` 보다 넉넉하게(예: +5초) 잡는 것을
권장합니다. 그래야 AI 서버가 504를 먼저 돌려주어 원인 구분이 가능합니다.

## 프로젝트 구조

```
app/
├── main.py                  앱 팩토리, 라우터/미들웨어/예외 핸들러 등록
├── api/
│   ├── health.py            /health, /ready
│   ├── errors.py            예외 → HTTP 응답 변환
│   ├── middleware.py        요청 로깅 (처리 시간 포함)
│   └── v1/
│       ├── router.py        v1 라우터 집약
│       ├── chat.py          POST /v1/chat
│       └── roadmap.py       POST /v1/roadmap
├── schemas/                 요청/응답 스키마 (camelCase 계약)
│   ├── base.py              CamelModel
│   ├── chat.py
│   ├── roadmap.py
│   └── error.py
├── services/                유스케이스. 검증·정규화 담당
│   ├── chat_service.py
│   └── roadmap_service.py
├── chains/                  LLM 호출 로직
│   ├── base.py              메시지 변환, 히스토리 절삭
│   ├── chat_chain.py
│   └── roadmap_chain.py
├── prompts/                 프롬프트 (코드와 분리)
│   ├── loader.py
│   ├── chat_system.txt
│   └── roadmap_system.txt
├── repositories/            자격증 DB 조회 (읽기 전용)
│   └── certifications.py
└── core/
    ├── config.py            설정 (.env)
    ├── logging.py
    ├── exceptions.py        도메인 예외 → 상태 코드 매핑
    ├── db.py                MySQL 연결 (동기 드라이버를 스레드로 감쌈)
    └── llm.py               LLM 클라이언트 + 예외 변환 가드

batch/
├── schema.sql               자격증 테이블 정의
└── sync_certifications.py   공공데이터포털 → MySQL 수집 스크립트
```

`chains/tools.py` 는 모델이 자격증 DB를 조회할 수 있게 하는 도구를 정의한다. 도구 없이 두면
모델이 학습 지식만으로 답해서 폐지되었거나 존재하지 않는 자격증을 지어낸다.

계층 규칙: `api → services → chains → core`. 역방향 의존은 없습니다.

- **api**: HTTP만 안다. 비즈니스 판단을 하지 않는다.
- **services**: 유스케이스. LLM 출력 검증·정규화를 여기서 한다.
- **chains**: LLM 호출과 프롬프트 조립. HTTP를 모른다.
- **core**: 설정·로깅·예외·모델 클라이언트. 다른 계층을 모른다.

## 설정

`.env` 로 조정합니다. 전체 목록은 `.env.example` 참고.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | (필수) | OpenAI API 키 |
| `MODEL_NAME` | `gpt-4o-mini` | 사용할 모델 |
| `TEMPERATURE` | `0.3` | 채팅 응답 다양성 (로드맵은 0.2 고정) |
| `REQUEST_TIMEOUT_SECONDS` | `20` | LLM 호출 타임아웃 |
| `MAX_RETRIES` | `2` | LLM 호출 재시도 횟수 |
| `MAX_HISTORY_MESSAGES` | `30` | 모델에 전달할 최근 대화 개수 |
| `MIN_ROADMAP_STEPS` / `MAX_ROADMAP_STEPS` | `3` / `8` | 로드맵 스텝 개수 범위 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `MYSQL_HOST` / `PORT` / `USER` / `PASSWORD` / `DB` | (필수) | 자격증 DB 접속 정보 |
| `MAX_CANDIDATES` | `12` | 한 번에 모델에 넘길 자격증 후보 수 |
| `MAX_FIELD_CHARS` | `400` | 설명 텍스트를 자르는 길이 |
| `DATA_GO_KR_SERVICE_KEY` | (배치만) | 공공데이터포털 서비스키 |

## 설계 메모

**왜 로드맵에만 구조화 출력을 쓰나.** 채팅은 자유 텍스트라 모델 응답을 그대로 쓰면 됩니다.
로드맵은 백엔드가 DB에 넣을 고정 스키마가 필요해서, `with_structured_output` 으로 형식을
강제합니다. 이렇게 하면 "JSON 파싱 → 실패 시 재시도" 를 직접 짜지 않아도 됩니다.

**왜 서비스 계층에서 다시 정규화하나.** 구조화 출력은 *형식*은 보장해도 *값*은 보장하지
않습니다. 모델이 `orderNo` 를 1,3,7 로 주거나 과거 날짜를 넣을 수 있습니다. 백엔드가 그대로
저장하는 데이터이므로 여기서 한 번 더 다듬습니다.

**왜 프롬프트를 .txt 로 분리했나.** 프롬프트는 코드보다 자주 바뀌고, 수정 주체가 개발자가
아닐 수도 있습니다. 분리해 두면 파이썬을 몰라도 문구를 고칠 수 있고, git diff 도 읽기 쉽습니다.

## 앞으로 할 일

- [ ] 백엔드 ↔ AI 서버 간 인증 (내부 토큰 헤더)
- [ ] 응답 스트리밍 (`POST /v1/chat/stream`)
- [ ] 시험 일정·출제 기준 RAG 연동
- [ ] Dockerfile 및 배포 설정
