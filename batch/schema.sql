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
    series_nm  VARCHAR(30)                -- 계열명 (기술사/기능장/기사/기능사). W/C는 NULL
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

-- 연도별·회차별 합격률. 종목코드로 certification 과 이어진다.
-- 한 회차에 필기/실기 두 행이 생기므로 시험구분까지 키에 넣는다.
--
-- API가 주는 합격률(passRate)은 저장하지 않는다. 응시자수·합격자수로 결정되는 값이라
-- 이행종속이 생기고(3NF 위반), 정정이 들어오면 두 값이 어긋날 수 있다.
-- 게다가 API 값은 "43%"처럼 소수점을 버리거나 18.75를 18.8로 반올림해 원본보다 부정확하다.
-- 조회할 때 SUM(합격자)/SUM(응시자)로 계산한다.
CREATE TABLE IF NOT EXISTS pass_rate (
    jm_cd         VARCHAR(10) NOT NULL,  -- 종목코드 (certification.jm_cd)
    impl_yy       SMALLINT    NOT NULL,  -- 시행년도
    impl_seq      VARCHAR(4)  NOT NULL,  -- 회차. 기능사 상시시험이 있어 세 자리까지 온다
    exam_typ      VARCHAR(4)  NOT NULL,  -- 필기 / 실기
    recpt_no_cnt  INT,                   -- 응시자수
    exam_pass_cnt INT,                   -- 합격자수
    PRIMARY KEY (jm_cd, impl_yy, impl_seq, exam_typ)
) DEFAULT CHARSET=utf8mb4;

-- 응시수수료. 검정형(국가기술·국가전문)에만 있다.
-- 원문이 "1차 : 19400, 2차 : 22600" 형태로 오는데, 1차만 있거나 3차까지 있는 종목이 있어
-- 차수별 컬럼으로 나눠 담는다. 613종목 전부 확인한 결과 차수·금액 외의 텍스트는 없다.
CREATE TABLE IF NOT EXISTS exam_fee (
    jm_cd VARCHAR(10) PRIMARY KEY,
    fee_1 INT,
    fee_2 INT,
    fee_3 INT
) DEFAULT CHARSET=utf8mb4;
