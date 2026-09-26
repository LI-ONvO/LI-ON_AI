# 백엔드가 AI 서버에 제공해야 하는 조회 API

AI 서버는 Vercel에서 돌고 자격증 DB는 서버 내부에 있어 직접 읽을 수 없다.
그래서 조회를 백엔드 API로 대신한다. (배치는 지금처럼 DB에 직접 쓴다. 변경 없음.)

```
플러터 → 백엔드 → AI 서버 → 백엔드(아래 API) → MySQL
```

## 공통

- 경로 접두사는 예시다. 바꿔도 되고, 정해지면 알려주면 AI 서버 설정만 고친다.
- 응답은 모두 camelCase.
- 인증: AI 서버가 `X-API-Key` 헤더에 약속된 값을 넣어 보낸다. 값은 따로 전달한다.
- 이 API들은 외부에 노출할 필요가 없다. AI 서버만 호출한다.
- **DB 행에 가까운 형태로 주면 된다.** 라벨 만들기, 지난 일정 표시 같은 가공은 AI 서버가 한다.

## 1. 자격증 검색

```
GET /internal/certifications/search?keywords=요리,조리&limit=12
```

챗봇이 "관심 분야"로 자격증을 찾을 때 쓴다. **정렬이 품질을 좌우하므로 아래 SQL을 그대로 써 달라.**

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
LIMIT :limit
```

- 키워드가 여러 개면 키워드마다 위 점수식을 더한다.
- **먼저 AND로 조회하고(모든 키워드가 걸린 종목), 0건이면 OR로 다시 조회한다.**
  OR만 쓰면 "정보처리 + 기능사"에 도배기능사 같은 게 딸려온다.
- `hist`(변천과정)에 점수를 주는 이유: 이름이 바뀐 자격증을 옛 이름으로 찾기 위해서다.
  예) "정보처리기능사" → 프로그래밍기능사

```json
{
  "results": [
    {
      "jmCd": "7910", "jmNm": "한식조리기능사", "seriesNm": "기능사",
      "mdobligFldNm": "조리", "job": "...", "summary": "...",
      "career": "...", "hist": "...", "score": 150
    }
  ]
}
```

## 2. 종목 찾기 (이름 또는 코드)

```
GET /internal/certifications/resolve?query=정보처리기사&limit=20
```

```sql
WHERE jm_cd = :query OR jm_nm LIKE CONCAT('%', :query, '%')
ORDER BY CASE WHEN jm_nm = :query THEN 0 ELSE 1 END, jm_nm
```

`total`은 **자르기 전 전체 개수**여야 한다. "기능사"처럼 넓은 검색어일 때 AI가
"3개뿐"이라고 오해하지 않도록 쓴다.

```json
{ "total": 2,
  "matches": [ { "jmCd": "1320", "jmNm": "정보처리기사", "qualGbCd": "T" } ] }
```

## 3. 종목 상세

```
GET /internal/certifications/1320
```

`certification` + `qual_detail`을 조인해서 그대로 준다. 없으면 404.

```json
{
  "jmCd": "1320", "jmNm": "정보처리기사", "qualGbCd": "T", "seriesNm": "기사",
  "mdobligFldNm": "정보기술", "career": "...", "job": "...", "summary": "...",
  "docFee": 19400, "pracFee": 22600,
  "docPassRate": 65.05, "pracPassRate": 22.1
}
```

`qual_detail`이 없는 종목(국가기술자격 외)은 상세 필드를 null로 채워 준다.

## 4. 추천 후보 목록

```
GET /internal/certifications/recommendable
```

메인 화면 추천에 쓴다. AI에게 목록 전체를 넘겨 DB에 없는 자격증을 지어내지 못하게 한다.

```sql
SELECT c.jm_cd, c.jm_nm, c.series_nm, d.mdoblig_fld_nm
FROM qual_detail d JOIN certification c ON c.jm_cd = d.jm_cd
WHERE c.qual_gb_cd = 'T'
ORDER BY d.mdoblig_fld_nm, c.jm_nm
```

약 491건. 페이지 나누지 말고 한 번에 준다.

```json
{ "results": [ { "jmCd": "1320", "jmNm": "정보처리기사",
                 "seriesNm": "기사", "mdobligFldNm": "정보기술" } ] }
```

## 5. 시험일정

```
GET /internal/certifications/1320/schedules?year=2026
```

`exam_schedule`의 행을 그대로 준다. 날짜는 `YYYY-MM-DD` 또는 null.
해당 연도 일정이 없으면 빈 배열(오류 아님).

```sql
SELECT description, impl_seq, doc_reg_start_dt, doc_reg_end_dt,
       doc_exam_start_dt, doc_exam_end_dt, doc_pass_dt,
       prac_reg_start_dt, prac_reg_end_dt,
       prac_exam_start_dt, prac_exam_end_dt, prac_pass_dt
FROM exam_schedule WHERE jm_cd = :jmCd AND impl_yy = :year
ORDER BY impl_seq, doc_reg_start_dt
```

```json
{
  "results": [
    { "description": "국가기술자격 기사 (2026년도 제3회)", "implSeq": "3",
      "docRegStartDt": "2026-07-20", "docRegEndDt": "2026-07-23",
      "docExamStartDt": "2026-08-22", "docExamEndDt": "2026-08-22",
      "docPassDt": "2026-10-07",
      "pracRegStartDt": "2026-08-31", "pracRegEndDt": "2026-11-09",
      "pracExamStartDt": "2026-11-14", "pracExamEndDt": "2026-11-28",
      "pracPassDt": "2026-12-11" }
  ]
}
```

## 주의

- **AI 서버가 백엔드를 다시 호출하는 구조**다. 백엔드가 AI 서버를 부르고 응답을 기다리는
  동안 AI 서버가 백엔드를 부르므로, 처리 스레드/커넥션이 부족하면 서로 기다리다 멈출 수 있다.
  동시 요청 수에 여유를 두는 것이 좋다.
- 챗봇 한 번에 이 API가 최대 4번까지 호출될 수 있다(도구 호출 상한).
