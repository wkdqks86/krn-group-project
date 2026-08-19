"""회귀 테스트 기준선을 다시 만든다.

엔진·문항·가중치를 **의도적으로** 바꿨을 때만 실행한다.
테스트가 깨졌다는 이유만으로 돌리면 회귀 테스트의 의미가 없어진다.

    python tests/regenerate_baseline.py

실행하면 tests/fixtures/persona_responses.json의 expected가 갱신되고,
무엇이 어떻게 바뀌었는지 화면에 찍힌다. 그 내용을 PR 설명에 붙여 넣으면 된다.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from domain.branching import build_user_profile, visible_question_queue  # noqa: E402
from domain.scoring import rank_job_families  # noqa: E402

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "persona_responses.json"


def main() -> int:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    questions = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
    job_profiles = json.loads((ROOT / "data" / "job_profiles.json").read_text(encoding="utf-8"))

    changed = False
    for persona in payload["personas"]:
        responses = persona["responses"]
        queue = visible_question_queue(questions, responses)
        user_vector, clusters = build_user_profile(questions, responses)
        ranked = rank_job_families(user_vector, job_profiles["job_families"], top_n=8)

        before = persona.get("expected", {})
        after = {
            "clusters": clusters,
            "visible_question_count": len(queue),
            "unanswered": [q["question_id"] for q in queue if q["question_id"] not in responses],
            "user_vector": {axis: round(value, 4) for axis, value in user_vector.items()},
            "ranking": [
                {
                    "rank": item["rank"],
                    "job_family_id": item["job_family_id"],
                    "name": item["name"],
                    "total": item["total"],
                    "band": item["band"],
                }
                for item in ranked
            ],
        }

        old_top3 = [i["name"] for i in before.get("ranking", [])[:3]]
        new_top3 = [i["name"] for i in after["ranking"][:3]]
        if old_top3 != new_top3:
            changed = True
            print(f"{persona['name']}  TOP 3 변경")
            print(f"   이전: {' → '.join(old_top3) or '(없음)'}")
            print(f"   이후: {' → '.join(new_top3)}")
        else:
            old_scores = {i["job_family_id"]: i["total"] for i in before.get("ranking", [])}
            diffs = [
                f"{i['name']} {old_scores[i['job_family_id']]}→{i['total']}"
                for i in after["ranking"]
                if i["job_family_id"] in old_scores and old_scores[i["job_family_id"]] != i["total"]
            ]
            if diffs:
                changed = True
                print(f"{persona['name']}  TOP 3는 그대로, 점수 변경")
                for line in diffs:
                    print(f"   {line}")
            else:
                print(f"{persona['name']}  변경 없음")

        if after["unanswered"]:
            print(f"   경고: 답이 빠진 문항이 있습니다 → {after['unanswered']}")
            print("   픽스처의 responses에 답을 채운 뒤 다시 실행하세요.")
            return 1

        persona["expected"] = after

    FIXTURE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n기준선을 갱신했습니다: {FIXTURE_PATH.relative_to(ROOT)}")
    if changed:
        print("위 변경 내용을 PR 설명의 '무엇을 바꿨나요'에 붙여 넣어 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
