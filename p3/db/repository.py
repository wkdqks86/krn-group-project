"""SQLite 접근 계층. SQL은 전부 여기에만 둔다.

도메인 모듈은 DB를 모르고, DB는 점수 계산을 모른다.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from p3.config import DB_PATH, ENGINE_VERSION, SCHEMA_PATH


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id():
    return str(uuid.uuid4())


@contextmanager
def connect(db_path=None):
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(db_path=None):
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        ddl = f.read()
    with connect(db_path) as conn:
        conn.executescript(ddl)


# --- 세션 -----------------------------------------------------------------


def create_session(consent_version, db_path=None):
    user_id, session_id, ts = new_id(), new_id(), now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (user_id, consent_version, created_at) VALUES (?, ?, ?)",
            (user_id, consent_version, ts),
        )
        conn.execute(
            "INSERT INTO diagnosis_sessions (session_id, user_id, status, started_at, engine_version)"
            " VALUES (?, ?, 'started', ?, ?)",
            (session_id, user_id, ts, ENGINE_VERSION),
        )
    return session_id


def set_session_status(session_id, status, completed=False, db_path=None):
    with connect(db_path) as conn:
        if completed:
            conn.execute(
                "UPDATE diagnosis_sessions SET status = ?, completed_at = ? WHERE session_id = ?",
                (status, now(), session_id),
            )
        else:
            conn.execute(
                "UPDATE diagnosis_sessions SET status = ? WHERE session_id = ?", (status, session_id)
            )


def get_session(session_id, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM diagnosis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


# --- 응답 -----------------------------------------------------------------


def save_response(session_id, question_id, value, shown_order=None, db_path=None):
    """같은 문항에 다시 답하면 덮어쓴다. 사용자가 앞 질문으로 돌아갈 수 있어야 하기 때문이다."""
    option_id = value if isinstance(value, str) else None
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO responses (session_id, question_id, option_id, value_json, shown_order, answered_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id, question_id) DO UPDATE SET"
            "   option_id = excluded.option_id,"
            "   value_json = excluded.value_json,"
            "   shown_order = excluded.shown_order,"
            "   answered_at = excluded.answered_at",
            (session_id, question_id, option_id, json.dumps(value, ensure_ascii=False), shown_order, now()),
        )


def load_answers(session_id, db_path=None):
    """{question_id: value} 형태로 되돌린다. 도메인 함수가 바로 먹을 수 있는 모양이다."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT question_id, value_json FROM responses WHERE session_id = ?", (session_id,)
        ).fetchall()
    return {r["question_id"]: json.loads(r["value_json"]) for r in rows}


# --- 프로파일 · 결과 --------------------------------------------------------


def save_profile(session_id, profile, db_path=None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO profiles (session_id, big5_json, riasec_json, competency_json, context_json,"
            " confidence, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            "   big5_json = excluded.big5_json, riasec_json = excluded.riasec_json,"
            "   competency_json = excluded.competency_json, context_json = excluded.context_json,"
            "   confidence = excluded.confidence, computed_at = excluded.computed_at",
            (
                session_id,
                json.dumps(profile["big5"], ensure_ascii=False),
                json.dumps(profile["riasec"], ensure_ascii=False),
                json.dumps(profile["competency"], ensure_ascii=False),
                json.dumps(profile["environment"], ensure_ascii=False) if profile["environment"] else None,
                profile["confidence"],
                now(),
            ),
        )


def save_recommendations(session_id, stage, ranked, versions, db_path=None):
    ts = now()
    with connect(db_path) as conn:
        conn.execute(
            "DELETE FROM recommendations WHERE session_id = ? AND stage = ?", (session_id, stage)
        )
        conn.executemany(
            "INSERT INTO recommendations (session_id, job_family_id, stage, rank, total, band,"
            " component_scores_json, reasons_json, engine_version, question_version,"
            " job_profile_version, copy_version, computed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    session_id,
                    r["job_family_id"],
                    stage,
                    r["rank"],
                    r["total"],
                    r["band"],
                    json.dumps(r["component_scores"], ensure_ascii=False),
                    json.dumps(r.get("reasons", []), ensure_ascii=False),
                    versions["engine_version"],
                    versions["question_version"],
                    versions["job_profile_version"],
                    versions["copy_version"],
                    ts,
                )
                for r in ranked
            ],
        )


def load_recommendations(session_id, stage, db_path=None):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE session_id = ? AND stage = ? ORDER BY rank",
            (session_id, stage),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["component_scores"] = json.loads(d.pop("component_scores_json"))
        d["reasons"] = json.loads(d.pop("reasons_json"))
        out.append(d)
    return out


# --- 직업 스냅샷 ------------------------------------------------------------


def upsert_occupation(occ, db_path=None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO occupations (occupation_id, job_family_id, external_code, name, source_url,"
            " source_label, snapshot_json, refreshed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(occupation_id) DO UPDATE SET"
            "   name = excluded.name, external_code = excluded.external_code,"
            "   source_url = excluded.source_url, source_label = excluded.source_label,"
            "   snapshot_json = excluded.snapshot_json, refreshed_at = excluded.refreshed_at",
            (
                occ["occupation_id"],
                occ["job_family_id"],
                occ.get("external_code"),
                occ["name"],
                occ.get("source_url"),
                occ.get("source_label"),
                json.dumps(occ.get("snapshot", {}), ensure_ascii=False),
                occ.get("refreshed_at") or now(),
            ),
        )


def load_occupations(job_family_id, db_path=None):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM occupations WHERE job_family_id = ? ORDER BY occupation_id", (job_family_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["snapshot"] = json.loads(d.pop("snapshot_json") or "{}")
        out.append(d)
    return out


# --- 로그 · 피드백 ----------------------------------------------------------


def log_api_fetch(source, request_hash, status, duration_ms=None, cache_key=None, db_path=None):
    """인증키와 요청 원문은 저장하지 않는다. 해시와 상태만 남긴다."""
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO api_fetch_logs (source, request_hash, status, duration_ms, fetched_at, cache_key)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (source, request_hash, status, duration_ms, now(), cache_key),
        )


def save_feedback(session_id, rating, reason=None, db_path=None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO feedback (session_id, rating, reason, created_at) VALUES (?, ?, ?, ?)",
            (session_id, rating, reason, now()),
        )


def log_event(session_id, name, screen=None, job_family_id=None, db_path=None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (session_id, name, screen, job_family_id, engine_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, name, screen, job_family_id, ENGINE_VERSION, now()),
        )
