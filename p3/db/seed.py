"""P2 JSON → SQLite seed.

앱 시작 시 실행한다. 여러 번 돌려도 같은 상태가 되도록 upsert로 짰다.
문항·직군 프로파일의 원본은 항상 Git의 JSON이고, SQLite는 그 사본이다.
"""
import json

from p3.config import OCCUPATION_SNAPSHOT_PATH
from p3.db import repository as repo
from p3.domain import content


def seed_questions(db_path=None):
    q = content.questions()
    version = q["question_version"]
    n_q = n_o = 0
    with repo.connect(db_path) as conn:
        for item in q["questions"]:
            conn.execute(
                "INSERT INTO questions (question_id, module, stage, prompt, type, axis, competency,"
                " reverse, cluster, branch_trigger, display_order, active_version)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(question_id) DO UPDATE SET"
                "   module = excluded.module, stage = excluded.stage, prompt = excluded.prompt,"
                "   type = excluded.type, axis = excluded.axis, competency = excluded.competency,"
                "   reverse = excluded.reverse, cluster = excluded.cluster,"
                "   branch_trigger = excluded.branch_trigger, display_order = excluded.display_order,"
                "   active_version = excluded.active_version",
                (
                    item["question_id"],
                    item["module"],
                    item["stage"],
                    item["prompt"],
                    item["type"],
                    item.get("axis"),
                    item.get("competency"),
                    1 if item.get("reverse") else 0,
                    item.get("cluster"),
                    1 if item.get("branch_trigger") else 0,
                    item.get("order"),
                    version,
                ),
            )
            n_q += 1
            for i, opt in enumerate(item.get("options", [])):
                # 현실 조건 문항(C01~C07)의 options는 점수가 없는 문자열 배열이다.
                # 화면에는 필요하므로 id를 만들어 저장하되 score_map은 비워 둔다.
                if isinstance(opt, str):
                    opt = {"option_id": f"{item['question_id']}-{i:02d}", "label": opt, "score_map": {}}
                conn.execute(
                    "INSERT INTO question_options (option_id, question_id, label, cluster,"
                    " score_map_json, option_order) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(option_id) DO UPDATE SET"
                    "   label = excluded.label, cluster = excluded.cluster,"
                    "   score_map_json = excluded.score_map_json, option_order = excluded.option_order",
                    (
                        opt["option_id"],
                        item["question_id"],
                        opt["label"],
                        opt.get("cluster"),
                        json.dumps(opt["score_map"], ensure_ascii=False),
                        i,
                    ),
                )
                n_o += 1
    return n_q, n_o


def seed_job_profiles(db_path=None):
    p = content.job_profiles()
    version = p["job_profile_version"]
    n = 0
    with repo.connect(db_path) as conn:
        for fam in p["job_families"]:
            conn.execute(
                "INSERT INTO job_families (job_family_id, name, description, active_version)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(job_family_id) DO UPDATE SET"
                "   name = excluded.name, description = excluded.description,"
                "   active_version = excluded.active_version",
                (fam["job_family_id"], fam["name"], fam["one_liner"], version),
            )
            conn.execute(
                "INSERT INTO job_profiles (job_family_id, vector_json, weight_json, environment_json,"
                " rationale, version) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(job_family_id) DO UPDATE SET"
                "   vector_json = excluded.vector_json, weight_json = excluded.weight_json,"
                "   environment_json = excluded.environment_json, rationale = excluded.rationale,"
                "   version = excluded.version",
                (
                    fam["job_family_id"],
                    json.dumps(
                        {
                            "competency": fam["competency_target"],
                            "riasec": fam["riasec_target"],
                            "big5": fam["big5_target"],
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "competency": fam["competency_weight"],
                            "riasec": fam["riasec_weight"],
                            "big5": fam["big5_weight"],
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(fam["environment"], ensure_ascii=False),
                    fam["rationale"],
                    version,
                ),
            )
            n += 1
    return n


def seed_occupations(db_path=None):
    """검수 스냅샷을 넣는다. P5가 Work24 조사로 이 파일을 갱신한다.

    스냅샷이 없어도 job_profiles.json의 occupations 이름만으로 최소 카드를 만든다.
    발표 중 상세 화면이 비는 것보다 이름만이라도 보이는 편이 낫다.
    """
    if OCCUPATION_SNAPSHOT_PATH.exists():
        with open(OCCUPATION_SNAPSHOT_PATH, encoding="utf-8") as f:
            snapshot = json.load(f)
        rows = snapshot["occupations"]
    else:
        rows = []
        for fam in content.job_profiles()["job_families"]:
            for i, name in enumerate(fam["occupations"], 1):
                rows.append(
                    {
                        "occupation_id": f"{fam['job_family_id']}-{i:02d}",
                        "job_family_id": fam["job_family_id"],
                        "name": name,
                        "source_label": "팀 작성 (Work24 매핑 전)",
                        "snapshot": {},
                    }
                )
    for occ in rows:
        repo.upsert_occupation(occ, db_path)
    return len(rows)


def run(db_path=None, verbose=True):
    repo.init_schema(db_path)
    nq, no = seed_questions(db_path)
    nf = seed_job_profiles(db_path)
    noc = seed_occupations(db_path)
    if verbose:
        v = content.versions()
        print(f"문항 {nq}개 · 선택지 {no}개 · 직군 {nf}개 · 연관직업 {noc}개 seed 완료")
        print(f"버전: {v}")
    return {"questions": nq, "options": no, "job_families": nf, "occupations": noc}
