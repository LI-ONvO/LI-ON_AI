# 백엔드가 AI 서버에 제공할 조회 API

AI 서버는 Vercel에서 돌고 자격증 DB는 서버 내부에 있어 직접 읽을 수 없다.
그래서 조회를 백엔드 API로 대신한다. (배치는 지금처럼 DB에 직접 쓴다. 변경 없음.)

```
플러터 → 백엔드 → AI 서버 → 백엔드(아래 API) → MySQL
```

엔드포인트는 4개이고, 그중 상세 조회는 이미 있는 것을 조금 넓히면 된다.

## 공통

- 기존 규칙을 따른다. 목록은 `content` / `totalElements` 형태, 필드명은 `name`, `category`.
- **인증**: AI 서버에는 로그인한 사용자가 없어 accessToken 을 만들 수 없다.
  공유 비밀값을 헤더로 보내는 방식을 제안한다.
  ```
  X-Internal-Key: {백엔드와 AI 서버만 아는 값}
  ```
  Bearer 를 쓰고 싶으면 AI 서버 전용 토큰을 하나 발급해 줘도 된다. 값은 따로 전달한다.
- 이 API들은 외부에 노출할 필요가 없다. AI 서버만 호출한다.
- **DB 행에 가까운 형태로 주면 된다.** 날짜 라벨 붙이기, 지난 일정 표시 같은 가공은 AI 서버가 한다.
- 날짜는 `YYYY-MM-DD` 또는 null.

## 1. 자격증 검색 (신규)

```
GET /api/certificates/search?keywords=요리,조리&size=12
X-Internal-Key: ...
```

챗봇이 "관심 분야"로 자격증을 찾을 때 쓴다. 지금 `/api/certificates` 의 `keyword` 와 달리
**이름만 보면 안 된다.** "보안 쪽 관심 있어"라고 하면 이름에 '보안'이 없는 종목도
직종·개요에서 찾아내야 한다.

```sql
SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm,
       d.job, d.summary, d.career, d.hist,
       (CASE WHEN c.jm_nm          LIKE :kw THEN 100 ELSE 0 END)
     + (CASE WHEN d.mdoblig_fld_nm LIKE :kw THEN  50 ELSE 0 END)
     + (CASE WHEN d.hist           LIKE :kw THEN  30 ELSE 0 END)
     + (CASE WHEN d.job            LIKE :kw THEN  10 ELSE 0 END)
     + (CASE WHEN d.summary        LIKE :kw THEN   3 ELSE 0 END)
     + (CASE WHEN d.career         LIKE :kw THEN   1 ELSE 0 END) AS score
FROM qual_detail d
JOIN certification c ON c.jm_cd = d.jm_cd
WHERE (위 6개 컬럼 중 하나라도 LIKE :kw)
ORDER BY score DESC, c.jm_nm
LIMIT :size
```

- `keywords` 는 쉼표로 구분된 2~5개. 키워드마다 위 점수식을 더한다.
- **먼저 AND 로 조회하고(모든 키워드가 걸린 종목), 0건이면 OR 로 다시 조회한다.**
  OR 만 쓰면 "정보처리 + 기능사" 에 도배기능사 같은 게 딸려온다.
- `hist`(변천과정)에 점수를 주는 이유: 이름이 바뀐 자격증을 옛 이름으로 찾기 위해서다.
  예) "정보처리기능사" → 프로그래밍기능사. 이게 빠지면 "그런 자격증 없다"고 답하게 된다.
- 설명 필드(job/summary/career/hist)를 같이 주는 이유: AI 가 추천 이유를 쓸 근거다.
  없으면 종목마다 상세를 다시 불러야 해서 한 번 검색에 API 호출이 12번씩 늘어난다.
- 길면 잘라도 된다. 필드당 400자면 충분하다.

```json
{
  "content": [
    { "jmCd": "7910", "name": "한식조리기능사", "seriesNm": "기능사",
      "mdobligFldNm": "조리", "job": "...", "summary": "...",
      "career": "...", "hist": "...", "score": 150 }
  ],
  "totalElements": 7
}
```

## 2. 종목 찾기 - 이름 또는 코드 (신규)

```
GET /api/certificates/resolve?query=정보처리기사&size=20
```

챗봇이 "정보처리기사 일정 알려줘" 처럼 특정 종목을 지목했을 때 쓴다.
검색과 달리 **전체 자격증**이 대상이다(국가전문·과정평가형·일학습병행 포함).

```sql
WHERE jm_cd = :query OR jm_nm LIKE CONCAT('%', :query, '%')
ORDER BY CASE WHEN jm_nm = :query THEN 0 ELSE 1 END, jm_nm
LIMIT :size
```

`totalElements` 는 **자르기 전 전체 개수**여야 한다. "기능사" 처럼 넓은 검색어일 때
AI 가 "3개뿐" 이라고 오해하지 않도록 쓴다.

```json
{
  "content": [ { "jmCd": "1320", "name": "정보처리기사", "qualGbCd": "T" } ],
  "totalElements": 2
}
```

`qualGbCd` 가 필요한 이유: 같은 이름이 자격구분만 다르게 존재한다.
(프로그래밍기능사 = 국가기술자격 6921 / 과정평가형 E921, 시험일정이 서로 다르다)

## 3. 종목 상세 (기존 API 확장)

```
GET /api/certificates/{jmCd}
```

이미 있는 것에 아래 다섯 필드만 추가해 주면 된다.

```
qualGbCd        T:국가기술 S:국가전문 W:일학습병행 C:과정평가형
seriesNm        계열명(기술사/기능장/기사/기능사). W·C 는 null
mdobligFldNm    직종
job             수행직무
career          진로 및 전망
```

`examSchedules` 는 지금 설계대로 상세에 포함하면 된다. 연도 거르기는 AI 서버가 한다.
`qual_detail` 이 없는 종목은 상세 필드를 null 로 채워 준다.

확인 부탁: 기존 응답의 `category` 와 `description` 이 각각 어느 값인지.
(`category` 가 계열명인지 자격구분인지, `description` 이 `summary` 인지 `job` 인지)

## 4. 추천 후보 목록 (신규)

```
GET /api/certificates/recommendable
```

메인 화면 추천에 쓴다. AI 에게 목록 **전체**를 넘겨 DB 에 없는 자격증을 지어내지 못하게 한다.
그래서 페이지를 나누면 안 되고, 3,680건 전체를 주어도 안 된다(프롬프트에 안 들어간다).

```sql
SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm
FROM qual_detail d JOIN certification c ON c.jm_cd = d.jm_cd
WHERE c.qual_gb_cd = 'T'
ORDER BY d.mdoblig_fld_nm, c.jm_nm
```

약 491건.

```json
{
  "content": [ { "jmCd": "1320", "name": "정보처리기사",
                 "seriesNm": "기사", "mdobligFldNm": "정보기술" } ],
  "totalElements": 491
}
```

## 주의

- **AI 서버가 백엔드를 다시 호출하는 구조**다. 백엔드가 AI 서버를 부르고 응답을 기다리는
  동안 AI 서버가 백엔드를 부르므로, 처리 스레드/커넥션이 부족하면 서로 기다리다 멈출 수 있다.
  동시 요청 수에 여유를 두는 것이 좋다.
- 챗봇 한 번에 1~4 번 호출된다(도구 호출 상한 4회).
