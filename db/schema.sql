-- 잠재력 발견 플랫폼 MVP — SQLite 스키마
-- PRD §12 ERD를 그대로 구현한다.
--
-- 원칙 세 가지
--   1. 응답 원문 · 계산 결과 · 콘텐츠 스냅샷을 분리한다. 재현성과 교체 가능성을 위해서다.
--   2. 개인 식별정보를 수집하지 않는다. user_id는 익명 UUID다.
--   3. 결과에는 engine_version · question_version · job_profile_version을 함께 저장한다.
--      가중치가 바뀌어도 과거 결과를 그대로 재현할 수 있다.

PRAGMA foreign_keys = ON;

-- 익명 사용자. 로그인·이름·연락처는 수집하지 않는다.
CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    consent_version  TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnosis_sessions (
    session_id       TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(user_id),
    status           TEXT NOT NULL CHECK (status IN ('started', 'completed', 'abandoned')),
    started_at       TEXT NOT NULL,
    completed_at     TEXT,
    engine_version   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON diagnosis_sessions(user_id);

-- 문항의 원본은 항상 data/questions.json이고, 이 표는 그 사본이다.
-- 관리자 UI는 MVP 범위 밖이다.
CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT PRIMARY KEY,
    module           TEXT NOT NULL,
    type             TEXT NOT NULL,
    axis             TEXT,
    cluster          TEXT,
    required         INTEGER NOT NULL DEFAULT 0,
    prompt           TEXT NOT NULL,
    active_version   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS question_options (
    option_id        TEXT PRIMARY KEY,
    question_id      TEXT NOT NULL REFERENCES questions(question_id),
    label            TEXT NOT NULL,
    cluster          TEXT,
    primary_axis     TEXT NOT NULL,
    secondary_axis   TEXT NOT NULL,
    option_order     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_options_question ON question_options(question_id);

-- 원응답과 노출 이력. 선택지 텍스트는 중복 저장하지 않는다.
CREATE TABLE IF NOT EXISTS responses (
    response_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL REFERENCES diagnosis_sessions(session_id),
    question_id      TEXT NOT NULL,
    option_id        TEXT,
    value_json       TEXT NOT NULL,
    shown_order      INTEGER,
    answered_at      TEXT NOT NULL,
    UNIQUE (session_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);

-- 12축 사용자 벡터. 세션당 하나이며 재계산 시 덮어쓴다.
CREATE TABLE IF NOT EXISTS profiles (
    session_id       TEXT PRIMARY KEY REFERENCES diagnosis_sessions(session_id),
    user_vector_json TEXT NOT NULL,
    clusters_json    TEXT NOT NULL,
    context_json     TEXT,
    optional_traits_json TEXT,
    computed_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_families (
    job_family_id    TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT,
    active_version   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_profiles (
    job_family_id    TEXT PRIMARY KEY REFERENCES job_families(job_family_id),
    requirement_vector_json TEXT NOT NULL,
    axis_weight_json TEXT NOT NULL,
    environment_json TEXT,
    rationale        TEXT,
    version          TEXT NOT NULL
);

-- 재현 가능한 결과. 계산에 쓰인 모든 버전을 함께 남긴다.
CREATE TABLE IF NOT EXISTS recommendations (
    session_id            TEXT NOT NULL REFERENCES diagnosis_sessions(session_id),
    job_family_id         TEXT NOT NULL REFERENCES job_families(job_family_id),
    rank                  INTEGER NOT NULL,
    total                 REAL NOT NULL,
    band                  TEXT NOT NULL,
    close_score           INTEGER NOT NULL DEFAULT 0,
    component_scores_json TEXT NOT NULL,
    cautions_json         TEXT NOT NULL,
    engine_version        TEXT NOT NULL,
    question_version      TEXT NOT NULL,
    job_profile_version   TEXT NOT NULL,
    computed_at           TEXT NOT NULL,
    PRIMARY KEY (session_id, job_family_id)
);
CREATE INDEX IF NOT EXISTS idx_recs_session ON recommendations(session_id, rank);

-- 직군 ↔ 연관 직업. snapshot_json이 API 실패 시의 fallback 원본이다.
CREATE TABLE IF NOT EXISTS occupations (
    occupation_id    TEXT PRIMARY KEY,
    job_family_id    TEXT NOT NULL REFERENCES job_families(job_family_id),
    external_code    TEXT,
    name             TEXT NOT NULL,
    source_url       TEXT,
    snapshot_json    TEXT,
    snapshot_date    TEXT,
    refreshed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_occupations_family ON occupations(job_family_id);

-- 운영·오류 추적. 인증키와 요청 원문은 절대 저장하지 않는다.
CREATE TABLE IF NOT EXISTS api_fetch_logs (
    log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    request_hash     TEXT NOT NULL,
    status           TEXT NOT NULL,
    duration_ms      INTEGER,
    fetched_at       TEXT NOT NULL
);

-- 제품 피드백. 점수 보정 근거로 쓰지 않는다.
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL REFERENCES diagnosis_sessions(session_id),
    rating           TEXT NOT NULL,
    reason           TEXT,
    created_at       TEXT NOT NULL
);

-- 분석 이벤트. 익명 session_id, 화면, 직군 ID, engine_version만 기록한다.
-- 학력·전공 원문과 선택지 텍스트는 중복 저장하지 않는다.
CREATE TABLE IF NOT EXISTS events (
    event_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    screen           TEXT,
    job_family_id    TEXT,
    engine_version   TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, name);
