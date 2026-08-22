"""P3 엔진 설정 — 경로, 버전, 외부 연동 스위치.

원칙: 비밀값은 코드에 두지 않는다. API 키는 환경변수나 Streamlit secrets에서만 읽는다.
키가 없으면 예외를 던지지 않고 mock 모드로 내려간다. 발표 중 키 문제로 화면이 깨지면 안 된다.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# P2 콘텐츠는 p3/data 에 둔다. 화면용 data/ 와 섞지 않는다.
DATA_DIR = Path(os.environ.get("PD_DATA_DIR", BASE_DIR / "data"))

QUESTIONS_PATH = DATA_DIR / "questions.json"
JOB_PROFILES_PATH = DATA_DIR / "job_profiles.json"
RESULT_COPY_PATH = DATA_DIR / "result_copy.json"

SNAPSHOT_DIR = BASE_DIR / "snapshots"
OCCUPATION_SNAPSHOT_PATH = SNAPSHOT_DIR / "occupations.json"

DB_PATH = Path(os.environ.get("PD_DB_PATH", BASE_DIR / "potential_discovery.db"))
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"

# 결과와 함께 저장되는 버전. 가중치가 바뀌어도 과거 결과를 재현할 수 있게 한다.
ENGINE_VERSION = "0.2"

# --- 외부 연동 -------------------------------------------------------------

WORK24_API_KEY = os.environ.get("WORK24_API_KEY") or ""
WORK24_JOB_INFO_URL = "https://apis.data.go.kr/1051000/job/openapi"
WORK24_RECRUIT_URL = "https://apis.data.go.kr/1051000/recruitment/openapi"

HTTP_TIMEOUT_SEC = 3.0
CACHE_TTL_SEC = 60
MAX_CALLS_PER_RESULT = 1


def work24_enabled() -> bool:
    """키가 없으면 API를 아예 시도하지 않는다. 스냅샷만으로 완결된다."""
    return bool(WORK24_API_KEY)


# --- LLM 설명 (선택) --------------------------------------------------------

LLM_ENABLED = os.environ.get("PD_LLM_ENABLED", "").lower() in ("1", "true", "yes")
LLM_TIMEOUT_SEC = 5.0
