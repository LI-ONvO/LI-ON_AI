-- 자격증 참조 데이터 스키마.
-- batch/sync_certifications.py 가 채우고, AI 서버는 읽기만 한다.
-- AI 서버가 실제로 읽는 컬럼만 둔다. 나중에 분야별 필터 같은 게 필요해지면
-- ALTER TABLE 로 컬럼을 늘리고 배치를 다시 돌리면 된다.

-- 전체 자격증 목록 (약 3,700건)
-- 이름 검색이 LIKE '%키워드%' 라 인덱스를 타지 못하고, 3,700행이면 전체를 훑어도 빠르므로
-- 별도 인덱스를 두지 않는다.
CREATE TABLE IF NOT EXISTS certification (
    jm_cd      VARCHAR(10)  PRIMARY KEY,  -- 종목코드
    jm_nm      VARCHAR(200) NOT NULL,     -- 종목명
    qual_gb_cd VARCHAR(2),                -- 자격구분 T:국가기술 S:국가전문 W:일학습병행 C:과정평가형
    series_nm  VARCHAR(30),               -- 계열명 (기술사/기능장/기사/기능사). W/C는 NULL

    -- 합격률(%). 최근 자료 기준으로 종목당 한 값만 담는다.
    -- 원본은 연도·회차·필기실기별로 나뉘고(2024년 한 해가 2,783행), 한 해 안에서도 회차마다
    -- 다르다(한식조리기능사 2024 필기: 1회 43.3% / 2회 43.0% / 3회 40.6%).
    -- 최신 연도부터 응시자 100명을 넘길 때까지 합쳐 "합격자 합 / 응시자 합"으로 계산한다.
    -- 회차나 연도의 퍼센트를 평균내지 않는다. 응시자 7명인 회차와 2,000명인 회차를 같은
    -- 무게로 다루면 실제와 어긋난다.
    -- 다 합쳐도 100명이 안 되는 희귀 종목(505개 중 61개)은 NULL로 둔다. 3명 중 3명 합격을
    -- "합격률 100%"로 보여주면 쉬운 자격증으로 오해하게 된다.
    doc_pass_rate  DECIMAL(5,2),  -- 필기. 실기만 있는 종목이나 표본 부족이면 NULL
    prac_pass_rate DECIMAL(5,2),  -- 실기. 실기가 없는 종목이나 표본 부족이면 NULL

    -- 응시수수료(원). 검정형(T/S)에만 있다.
    -- 3차까지 있는 국가전문자격이 8종목 있으나 담을 컬럼이 없어 버린다.
    doc_fee  INT,  -- 1차(필기)
    prac_fee INT   -- 2차(실기)
) DEFAULT CHARSET=utf8mb4;

-- 국가기술자격 상세 설명 (약 490건). 챗봇이 추천 이유를 설명할 때 쓴다.
CREATE TABLE IF NOT EXISTS qual_detail (
    jm_cd          VARCHAR(10) PRIMARY KEY,
    mdoblig_fld_nm VARCHAR(200),  -- 직종
    career         TEXT,          -- 진로 및 전망
    job            TEXT,          -- 수행직무
    summary        TEXT,          -- 개요
    trend          TEXT,          -- 출제경향
    hist           TEXT           -- 변천과정 (폐지된 옛 종목명이 남아있어 옛 이름 검색에 쓴다)
) DEFAULT CHARSET=utf8mb4;

-- 회차별 시험일정.
--
-- 일정은 종목마다 다르다. 같은 '기사' 계열이라도 정보처리기사는 연 3회(6행),
-- 정밀화학기사는 연 1회(2행), 의공기사는 2회(4행)로 제각각이고,
-- 2026년 일정이 아예 없는 종목도 많다(특히 일학습병행자격).
-- 그래서 계열 단위로 묶지 않고 종목코드별로 저장한다.
--
-- 같은 회차라도 정기접수와 빈자리접수가 따로 내려와 여러 행이 되므로 접수 시작일까지 PK에 넣는다.
-- (예: 정보처리기사 2026년 제3회는 접수기간이 07-20~23, 08-01~02 두 건이고 시험일은 같다.
--  API에 "정기/빈자리" 구분 필드가 없어 이 둘을 가를 수 있는 값이 접수 시작일뿐이다.)
--
-- 그런데 상시 시험처럼 필기 없이 실기만 있는 회차는 접수 시작일이 비고, PK 컬럼은 NULL이 될 수 없다.
-- 그렇다고 UNIQUE 로만 두면 MySQL이 NULL을 서로 다른 값으로 봐서 중복 검사에 걸리지 않고,
-- 배치를 돌릴 때마다 같은 일정이 새로 쌓인다.
-- 그래서 실제 날짜 컬럼은 NULL을 허용하고, 중복 판정용 값(reg_key)을 따로 계산해서 PK에 넣는다.
CREATE TABLE IF NOT EXISTS exam_schedule (
    jm_cd              VARCHAR(10) NOT NULL,  -- 종목코드 (certification.jm_cd)
    impl_yy            SMALLINT    NOT NULL,  -- 시행년도
    impl_seq           VARCHAR(4)  NOT NULL,  -- 회차
    doc_reg_start_dt   DATE,                  -- 필기 원서접수 시작. 없으면 NULL
    -- 중복 판정에만 쓰는 값. INSERT 하지 않는다. DB가 위 컬럼을 보고 자동으로 채운다.
    reg_key            DATE AS (IFNULL(doc_reg_start_dt, '1000-01-01')) STORED,
    description        VARCHAR(200),          -- 예: "국가기술자격 기사 (2026년도 제3회)"

    -- doc_* = 필기, prac_* = 실기.
    -- 각 단계마다 접수기간(시작~끝), 시험기간(시작~끝), 합격발표일이 있다.
    doc_reg_end_dt     DATE,                  -- 필기 원서접수 마감
    doc_exam_start_dt  DATE,                  -- 필기 시험 시작
    doc_exam_end_dt    DATE,                  -- 필기 시험 종료
    doc_pass_dt        DATE,                  -- 필기 합격발표
    prac_reg_start_dt  DATE,                  -- 실기 원서접수 시작
    prac_reg_end_dt    DATE,                  -- 실기 원서접수 마감
    prac_exam_start_dt DATE,                  -- 실기 시험 시작
    prac_exam_end_dt   DATE,                  -- 실기 시험 종료
    prac_pass_dt       DATE,                  -- 실기 합격발표
    PRIMARY KEY (jm_cd, impl_yy, impl_seq, reg_key)
) DEFAULT CHARSET=utf8mb4;


