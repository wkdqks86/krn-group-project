"""data/*.json → SQLite seed.

앱 시작 시 한 번 부른다. 여러 번 돌려도 같은 상태가 되도록 upsert로 짰다.
문항·직군 프로파일의 원본은 항상 Git의 JSON이고, SQLite는 그 사본이다.

    python -m db.seed          DB 생성 + seed
    python -m db.seed --check  seed 없이 데이터 정합성만 확인
"""

from __future__ import annotations

import json
from pathlib import Path

from db import repository as repo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def versions() -> dict[str, str]:
    """결과 레코드에 함께 저장할 버전 묶음."""
    from domain.scoring import ENGINE_VERSION

    return {
        "engine_version": ENGINE_VERSION,
        "question_version": load("questions.json")["question_version"],
        "job_profile_version": load("job_profiles.json")["job_profile_version"],
        "occupation_version": load("occupations.json")["occupation_version"],
        "copy_version": load("copy.json")["copy_version"],
    }


def seed_questions(db_path=None) -> tuple[int, int]:
    payload = load("questions.json")
    version = payload["question_version"]
    question_count = option_count = 0

    with repo.connect(db_path) as conn:
        for item in payload["questions"]:
            conn.execute(
                "INSERT INTO questions (question_id, module, type, axis, cluster, required, prompt,"
                " active_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(question_id) DO UPDATE SET"
                "   module = excluded.module, type = excluded.type, axis = excluded.axis,"
                "   cluster = excluded.cluster, required = excluded.required,"
                "   prompt = excluded.prompt, active_version = excluded.active_version",
                (
                    item["question_id"],
                    item["module"],
                    item["type"],
                    item.get("axis"),
                    item.get("cluster"),
                    1 if item.get("required") else 0,
                    item["prompt"],
                    version,
                ),
            )
            question_count += 1

            for order, option in enumerate(item.get("options", [])):
                conn.execute(
                    "INSERT INTO question_options (option_id, question_id, label, cluster,"
                    " primary_axis, secondary_axis, option_order) VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(option_id) DO UPDATE SET"
                    "   label = excluded.label, cluster = excluded.cluster,"
                    "   primary_axis = excluded.primary_axis,"
                    "   secondary_axis = excluded.secondary_axis,"
                    "   option_order = excluded.option_order",
                    (
                        option["option_id"],
                        item["question_id"],
                        option["label"],
                        option.get("cluster"),
                        option["primary"],
                        option["secondary"],
                        order,
                    ),
                )
                option_count += 1

    return question_count, option_count


def seed_job_profiles(db_path=None) -> int:
    payload = load("job_profiles.json")
    version = payload["job_profile_version"]

    with repo.connect(db_path) as conn:
        for family in payload["job_families"]:
            conn.execute(
                "INSERT INTO job_families (job_family_id, name, description, active_version)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(job_family_id) DO UPDATE SET"
                "   name = excluded.name, description = excluded.description,"
                "   active_version = excluded.active_version",
                (family["job_family_id"], family["name"], family.get("description"), version),
            )
            conn.execute(
                "INSERT INTO job_profiles (job_family_id, requirement_vector_json, axis_weight_json,"
                " environment_json, rationale, version) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(job_family_id) DO UPDATE SET"
                "   requirement_vector_json = excluded.requirement_vector_json,"
                "   axis_weight_json = excluded.axis_weight_json,"
                "   environment_json = excluded.environment_json,"
                "   rationale = excluded.rationale, version = excluded.version",
                (
                    family["job_family_id"],
                    json.dumps(family["requirement_vector"], ensure_ascii=False),
                    json.dumps(family["axis_weight"], ensure_ascii=False),
                    json.dumps(family.get("environment_json"), ensure_ascii=False),
                    family.get("rationale"),
                    version,
                ),
            )
    return len(payload["job_families"])


def seed_occupations(db_path=None) -> int:
    payload = load("occupations.json")
    snapshot_date = payload.get("snapshot_date")

    with repo.connect(db_path) as conn:
        for item in payload["occupations"]:
            conn.execute(
                "INSERT INTO occupations (occupation_id, job_family_id, external_code, name,"
                " source_url, snapshot_json, snapshot_date, refreshed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(occupation_id) DO UPDATE SET"
                "   job_family_id = excluded.job_family_id, external_code = excluded.external_code,"
                "   name = excluded.name, source_url = excluded.source_url,"
                "   snapshot_json = excluded.snapshot_json, snapshot_date = excluded.snapshot_date,"
                "   refreshed_at = excluded.refreshed_at",
                (
                    item["occupation_id"],
                    item["job_family_id"],
                    item.get("external_code"),
                    item["name"],
                    item.get("source_url"),
                    json.dumps(item.get("snapshot_json", {}), ensure_ascii=False),
                    snapshot_date,
                    repo.now(),
                ),
            )
    return len(payload["occupations"])


def check() -> list[str]:
    """seed 전에 데이터끼리 어긋난 곳이 없는지 본다. 문제가 있으면 목록을 돌려준다."""
    problems = []
    questions = load("questions.json")
    profiles = load("job_profiles.json")
    occupations = load("occupations.json")

    family_ids = {f["job_family_id"] for f in profiles["job_families"]}
    for item in occupations["occupations"]:
        if item["job_family_id"] not in family_ids:
            problems.append(
                f"occupations.json의 {item['occupation_id']}가 없는 직군을 가리킵니다: {item['job_family_id']}"
            )

    seen_questions, seen_options = set(), set()
    for item in questions["questions"]:
        if item["question_id"] in seen_questions:
            problems.append(f"문항 ID가 중복입니다: {item['question_id']}")
        seen_questions.add(item["question_id"])
        for option in item.get("options", []):
            if option["option_id"] in seen_options:
                problems.append(f"선택지 ID가 중복입니다: {option['option_id']}")
            seen_options.add(option["option_id"])

    axes = set(profiles["axes"])
    for family in profiles["job_families"]:
        missing = axes - set(family["requirement_vector"])
        if missing:
            problems.append(f"{family['job_family_id']}의 requirement_vector에 빠진 축: {sorted(missing)}")
        weight_sum = sum(family["axis_weight"].values())
        if abs(weight_sum - 1.0) > 1e-6:
            problems.append(f"{family['job_family_id']}의 axis_weight 합이 1.0이 아닙니다: {weight_sum}")

    return problems


def run(db_path=None, verbose: bool = True) -> dict[str, int]:
    problems = check()
    if problems:
        raise ValueError("데이터 정합성 문제:\n  - " + "\n  - ".join(problems))

    repo.init_schema(db_path)
    question_count, option_count = seed_questions(db_path)
    family_count = seed_job_profiles(db_path)
    occupation_count = seed_occupations(db_path)

    if verbose:
        print(f"문항 {question_count} · 선택지 {option_count} · 직군 {family_count} · 연관직업 {occupation_count} seed 완료")
        print(f"버전: {versions()}")

    return {
        "questions": question_count,
        "options": option_count,
        "job_families": family_count,
        "occupations": occupation_count,
    }


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        found = check()
        if found:
            print("데이터 정합성 문제:")
            for line in found:
                print(f"  - {line}")
            raise SystemExit(1)
        print("데이터 정합성 이상 없음")
        raise SystemExit(0)

    run()
