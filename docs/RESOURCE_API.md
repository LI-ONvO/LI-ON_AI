# 학습 자료 추천 API

자격증 공부에 쓸 **영상(YouTube) · 책(다음 책) · 웹사이트(NAVER 웹문서) · 블로그(NAVER 블로그)** 를 찾아 준다.

> **이 API 는 AI 를 쓰지 않는다.** 검색 API 약관 때문이다.
> - 카카오: "검색 데이터를 외부 LLM API 로 전송하여 활용하는 것은 제한" (2026-09-07 데브톡 공식 답변)
> - NAVER: 검색 API 데이터는 가공 없이 독립적으로 노출 (2026-09-07 개정 약관)
>
> 그래서 자료는 코드 규칙으로 고르고, `reason` 도 API 가 준 값(채널·길이·조회수·출판사·날짜)으로 만든다.
> `title`, `description` 은 API 가 준 그대로다(검색어 강조 태그 `<b>` 만 벗김).

---

## Request

- **Method:** `POST`
- **Endpoint:** `{AI_SERVER_URL}/resources/recommendations`

## Request Header

```
Content-Type: application/json
X-API-Key: {AI 서버 API 키}        // 없거나 틀리면 401
```

## Request Elements

```jsonc
{
  "userId": 1,                      // number, 선택. 로그 추적용. 결과에는 영향 없음
  "size": 8,                        // number, 선택(기본 8, 1~40). 돌려받을 자료 개수 (모든 종류 합)
  "certificate": {                  // 필수
    "jmCd": "6921",                 // string, 필수. 종목코드
    "name": "프로그래밍기능사"         // string, 선택. 종목명. 이 이름으로 검색한다. 없으면 jmCd 로 조회해서 채운다
  },
  "context": {                      // 선택
    "sessionId": 1,                 // number, 선택. 로그 추적용
    "roadmapSteps": [               // string[], 선택. 로드맵 스텝 제목들
      "필기 이론 1회독",              //   스텝이 전부 "필기" 얘기면 필기 자료를,
      "필기 기출 풀이"               //   전부 "실기" 얘기면 실기 자료를 찾는다. 섞여 있으면 구분하지 않는다
    ]
  },
  "excludeUrls": [                  // string[], 선택. 이미 보여 준 자료의 url. 결과에서 뺀다 ("더 보기"용)
    "https://www.youtube.com/watch?v=4-ilbOhj5QU"
  ],
  "types": ["VIDEO", "BOOK"]        // string[], 선택 (명세 외 추가). 받을 자료 종류. 없으면 네 종류 모두
                                    //   VIDEO | BOOK | WEB | BLOG
}
```

---

## Response

### 200 OK

- 실제 접근 가능한 url 만 반환한다. 검증에 실패한 항목은 뺀다.
- 종류를 **VIDEO → BOOK → WEB → BLOG** 순서로 번갈아 담는다. 한 종류가 모자라면 남은 종류로 채운다.
- 조건에 맞는 자료가 부족하면 `size` 보다 적게 올 수 있다. 0개일 수도 있다.
- 한 종류의 검색이 실패해도 나머지 종류로 응답한다. 실패한 종류는 `unavailable` 에 담긴다.

```jsonc
{
  "items": [
    // ───────────── 영상 (YouTube) ─────────────
    {
      "type": "VIDEO",                                    // 자료 종류
      "title": "[프로그래밍기능사 필기] [01-01-01] C언어 기본, printf, 변수와 자료형, scanf",  // 영상 제목 (원본 그대로)
      "url": "https://www.youtube.com/watch?v=4-ilbOhj5QU",                                 // 영상 주소
      "reason": "이기적 영진닷컴 · 53분 · 조회수 12,480회 · 2025-12-04 업로드",                // 한 줄 설명 (채널 · 길이 · 조회수 · 업로드일)
      "description": "★ 이 동영상은 [이기적 프로그래밍기능사] 도서 내용을 바탕으로 …",           // 영상 설명란 원문. 없으면 null
      "source": "YouTube · 이기적 영진닷컴",               // 출처 표기 (화면에 꼭 보여 줄 것)
      "thumbnailUrl": "https://i.ytimg.com/vi/4-ilbOhj5QU/hqdefault.jpg",  // 썸네일. 없으면 null
      "publishedAt": "2025-12-04T02:32:04Z",              // 업로드 시각 (UTC, ISO 8601 날짜+시간)
      "video": {
        "videoId": "4-ilbOhj5QU",                         // 영상 ID. 앱 안 플레이어(youtube_player 등)에 쓴다
        "channelId": "UCIimf8pEC9AP0N_9FGW_P_w",          // 채널 ID. 채널 주소 = https://www.youtube.com/channel/{channelId}
        "channelTitle": "이기적 영진닷컴",                  // 채널 이름
        "durationSeconds": 3213,                          // 영상 길이 (초)
        "viewCount": 12480,                               // 조회수. 채널이 숨겼으면 null
        "likeCount": 116,                                 // 좋아요 수. 숨겼으면 null
        "commentCount": 19,                               // 댓글 수. 댓글을 막았으면 null
        "tags": ["이기적", "영진닷컴", "…"],                // 업로더가 단 태그. 채널 공통 태그가 섞여 있어(다른 자격증 이름 등) 화면 표시는 권하지 않음
        "embeddable": true                                // 앱 안에서 재생(임베드) 가능 여부. false 면 YouTube 앱/브라우저로 열 것
      },
      "book": null,                                       // 영상이 아니면 아래 해당 객체만 채워지고 나머지는 null
      "blog": null
    },

    // ───────────── 책 (다음 책 / 카카오) ─────────────
    {
      "type": "BOOK",
      "title": "2027 기분좋은 프로그래밍기능사 필기 한 권에 합격",       // 책 제목 (원본 그대로)
      "url": "https://search.daum.net/search?w=bookpage&bookId=7290437&q=…",  // 다음 책 상세 페이지
      "reason": "시대고시기획 · 2027년 판 · 2027-01 출간",              // 한 줄 설명 (출판사 · 판 연도 · 출간월)
      "description": "1. 핵심이론 수록: 시험에 필수적으로 출제되는 …",      // 출판사 책 소개 일부 (원문, 끝이 잘려 있음). 없으면 null
      "source": "다음 책",
      "thumbnailUrl": "https://search1.kakaocdn.net/thumb/R120x174.q85/?fname=…",  // 표지 이미지 (120x174). 없으면 null
      "publishedAt": "2027-01-05",                        // 출간일 (날짜만). 예약판매 책은 미래 날짜일 수 있음
      "video": null,
      "book": {
        "authors": ["강희영"],                             // 저자 목록
        "translators": [],                                // 역자 목록 (보통 비어 있음)
        "publisher": "시대고시기획",                        // 출판사
        "isbn": "1143419820 9791143419828",               // ISBN. 10자리와 13자리가 공백으로 이어져 올 수 있음
        "price": 20000,                                   // 정가 (원)
        "salePrice": 18000,                               // 판매가 (원). 판매가 정보가 없으면 null
        "status": "정상판매",                               // 판매 상태. 판매 중인 책만 오므로 사실상 항상 "정상판매"
        "editionYear": 2027                               // 수험서 판 연도 (제목 앞 "2027"). 제목에 연도가 없으면 null
      },
      "blog": null
    },

    // ───────────── 웹사이트 (NAVER 웹문서) ─────────────
    {
      "type": "WEB",
      "title": "프로그래밍기능사 - 국가자격 종목별 상세정보",               // 페이지 제목 (원본 그대로)
      "url": "https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd=6921",
      "reason": "q-net.or.kr · 공식 기관",                 // 한 줄 설명 (도메인 [· 공식 기관])
      "description": "프로그래밍기능사는 과학기술정보통신부 소관이며 한국산업인력공단이 시행합니다. …",  // 검색 결과 미리보기 문구 (원문). 없으면 null
      "source": "NAVER 웹문서",
      "thumbnailUrl": null,                               // 웹문서는 항상 null
      "publishedAt": null,                                // 웹문서는 항상 null (API 가 주지 않음)
      "video": null,
      "book": null,
      "blog": null
    },

    // ───────────── 블로그 (NAVER 블로그) ─────────────
    {
      "type": "BLOG",
      "title": "[프로그래밍기능사 필기] 비전공자 공부법과 합격 준비 전략",   // 글 제목 (원본 그대로)
      "url": "https://blog.naver.com/sidaeedusharp/224404719988",
      "reason": "NAVER 블로그 · 시대에듀# 공식 블로그 · 2026-09-08 작성",  // 한 줄 설명 (블로그 이름 · 작성일)
      "description": "무엇이 달라졌고, 비전공자는 어떤 순서로 공부하면 좋을지 정리해 드립니다 …",  // 글 미리보기 문구 (원문). 없으면 null
      "source": "NAVER 블로그",
      "thumbnailUrl": null,                               // 블로그는 항상 null (API 가 주지 않음)
      "publishedAt": "2026-09-08",                        // 작성일 (날짜만)
      "video": null,
      "book": null,
      "blog": {
        "bloggerName": "시대에듀# 공식 블로그",              // 블로그 이름 (원본 그대로)
        "bloggerLink": "https://blog.naver.com/sidaeedusharp"  // 블로그 주소. 없으면 null
      }
    }
  ],

  "unavailable": [                  // 이번에 검색하지 못한 종류와 이유. 모두 정상이면 빈 배열 []
    {
      "type": "VIDEO",              // 어떤 종류가
      "reason": "QUOTA_EXCEEDED"    // 왜 빠졌는지
                                    //   QUOTA_EXCEEDED : 외부 API 호출 한도를 다 씀 → 시간이 지나면 풀림
                                    //                    (YouTube 는 매일 오후 4시, 서머타임 끝나면 오후 5시)
                                    //   NOT_CONFIGURED : AI 서버에 그 API 키가 없음 → AI 서버 담당에게 알릴 것
                                    //   ERROR          : 그 외 실패 (외부 API 장애, 시간 초과 등)
    }
  ]
}
```

> `items` 에 어떤 종류가 없을 때, `unavailable` 에 그 종류가 **없으면** "검색 결과가 없음", **있으면** "검색을 못 함"이다.
> 예: 영상 탭이 비었고 `unavailable` 에 `VIDEO / QUOTA_EXCEEDED` 가 있으면 "잠시 후 다시 시도해 주세요"를 보여 주면 된다.

### 오류

모든 오류 응답은 `{"code": "...", "message": "...", "detail": ...}` 형태다.

| HTTP | code | 언제 | 앱에서 |
|---|---|---|---|
| 401 | `UNAUTHORIZED` | `X-API-Key` 가 없거나 틀림 | 백엔드 설정 확인 |
| 422 | `INVALID_REQUEST` | 요청 형식이 틀림 (`certificate` 없음, `size` 범위 밖 등). `detail` 에 틀린 필드가 있음 | 요청 수정 |
| 422 | `CERTIFICATE_NOT_FOUND` | `certificate.name` 이 없고 `jmCd` 로도 자격증을 못 찾음 | 종목코드 확인 |
| 502 | `BACKEND_UNAVAILABLE` | `name` 이 없어 백엔드에서 자격증을 조회하다 실패 | 잠시 후 재시도 |
| 502 | `RESOURCE_SOURCES_UNAVAILABLE` | 요청한 **모든** 종류의 검색이 실패 (한도 초과가 아닌 이유 포함) | 잠시 후 재시도 |
| 503 | `RESOURCE_QUOTA_EXCEEDED` | 요청한 **모든** 종류가 호출 한도 초과 | "잠시 후 다시 시도해 주세요" |

---

## 자료를 고르는 규칙

| 종류 | 검색어 | 남기는 조건 | 순서 |
|---|---|---|---|
| VIDEO | `{종목명} [필기/실기] 강의` | 공개 영상 · 3분 이상(쇼츠 제외) · 3년 이내 · 제목에 종목명 포함 | YouTube 검색 관련도 순 |
| BOOK | `{종목명}` (제목 검색) | 판매 중 · 3년 이내 출간 · 제목에 종목명 포함 · 같은 ISBN 은 하나만 | 최신 판 연도 → 최근 출간 |
| WEB | `{종목명}` | 제목에 종목명 포함 · 사이트당 하나 | 공식 기관(q-net.or.kr 등) 먼저 → 검색 순 |
| BLOG | `{종목명} [필기/실기] 공부법` | 2년 이내 · 제목에 종목명 포함 · 블로거당 하나 · "학원·수강·모집·국비·할인·상담" 등이 들어간 홍보 글 제외 | 검색 관련도 순 |

- 종목명 비교는 띄어쓰기를 무시한다 ("프로그래밍 기능사"도 포함으로 본다).
- WEB·BLOG 는 링크를 실제로 열어 본다. 없는 페이지(404 등)나 연결 실패는 뺀다.
  봇 접근만 막는 사이트(401·403·429)는 페이지가 있다고 보고 남긴다.

## 앱 화면에 꼭 지킬 것 (약관)

- **출처(`source`)를 보여 주고, 누르면 원본(`url`)으로 이동**하게 한다. NAVER·카카오 약관 조건이다.
- `title`, `description` 을 고치거나 다른 출처 내용과 합쳐서 새 글처럼 보여 주지 않는다.
- 결과를 오래 저장하지 않는다. 저장 상한: YouTube 30일, NAVER 21일, 카카오는 임시 캐시만.

## 호출 한도

| 출처 | 한도 | 초기화 |
|---|---|---|
| YouTube | 하루 10,000점 (검색 100점 → **하루 약 100번**) | 매일 태평양 자정 (한국 오후 4시, 서머타임이 아니면 오후 5시) |
| NAVER (웹문서·블로그 합산) | 월 775,000번, 초당 50번 | 매월 |
| 카카오 책 | 일·월 한도 (카카오 디벨로퍼스 콘솔에서 확인) | — |

- 한도가 차면 AI 서버는 그 출처를 **풀릴 때까지 부르지 않고** 바로 `unavailable` 로 알린다.
- 같은 검색은 AI 서버가 6시간 동안 메모리에 들고 있다가 재사용한다. 다만 Vercel 인스턴스가 바뀌면 사라진다.
  사용자가 늘면 YouTube 한도가 먼저 바닥나므로, **백엔드 저장소(검색 결과 7일 보관)** 가 필요하다.
