"""P2 콘텐츠 파일 로더.

앱 시작 시 한 번만 읽고 캐시한다. 파일이 없거나 깨지면 즉시 예외를 던진다.
콘텐츠 없이 돌아가는 것보다, 시작 시점에 크게 실패하는 편이 낫다.
"""
import json
from functools import lru_cache

from p3.config import JOB_PROFILES_PATH, QUESTIONS_PATH, RESULT_COPY_PATH


def _load(path):
    if not path.exists():
        raise FileNotFoundError(
            f"P2 콘텐츠 파일이 없습니다: {path}\n"
            f"PD_DATA_DIR 환경변수로 p3/data 경로를 지정하세요."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def questions():
    return _load(QUESTIONS_PATH)


@lru_cache(maxsize=1)
def job_profiles():
    return _load(JOB_PROFILES_PATH)


@lru_cache(maxsize=1)
def result_copy():
    return _load(RESULT_COPY_PATH)


@lru_cache(maxsize=1)
def question_map():
    return {q["question_id"]: q for q in questions()["questions"]}


@lru_cache(maxsize=1)
def axes():
    return job_profiles()["axes"]


@lru_cache(maxsize=1)
def versions():
    """결과 레코드에 함께 저장할 버전 묶음."""
    from p3.config import ENGINE_VERSION

    return {
        "engine_version": ENGINE_VERSION,
        "question_version": questions()["question_version"],
        "job_profile_version": job_profiles()["job_profile_version"],
        "copy_version": result_copy()["copy_version"],
    }


def core_questions():
    """코어 문항을 order 순으로 반환한다."""
    qs = [q for q in questions()["questions"] if q["stage"] == "core"]
    return sorted(qs, key=lambda q: q["order"])


def deep_questions(module=None):
    qs = [q for q in questions()["questions"] if q["stage"] == "deep"]
    if module:
        qs = [q for q in qs if q["module"] == module]
    return qs


def reset_cache():
    """테스트에서 콘텐츠를 바꿔 끼울 때 쓴다."""
    for fn in (questions, job_profiles, result_copy, question_map, axes, versions):
        fn.cache_clear()
