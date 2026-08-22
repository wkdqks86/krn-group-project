"""P3 엔진 CLI.

    python -m p3.manage seed     DB 생성 + P2 JSON seed (여러 번 돌려도 안전)
    python -m p3.manage demo     진단 시작부터 직군 상세까지 한 번 흘려본다
    python -m p3.manage check    P2 기준선과 대조하고 결과만 출력한다
    python -m p3.manage offline  네트워크가 죽은 상태를 흉내 내 데모를 돌린다 (리허설용)
"""
import json
import sys
from pathlib import Path

from p3 import engine
from p3.db import seed as seeder
from p3.domain import branching, profile as profile_mod, scoring

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "persona_fixtures.json"


def cmd_seed():
    result = seeder.run(verbose=True)
    return 0 if result["job_families"] == 10 else 1


def _demo(persona_id="minji"):
    personas = json.loads(FIXTURES.read_text(encoding="utf-8"))["personas"]
    persona = next(p for p in personas if p["id"] == persona_id)

    engine.bootstrap()
    sid = engine.start_session()
    print(f"세션 시작 · {persona['name']} — {persona['summary']}\n")

    for i, (qid, val) in enumerate(persona["core_answers"].items(), 1):
        engine.answer(sid, qid, val, shown_order=i)
    prog = engine.core_progress(sid)
    print(f"코어 {prog['answered']}/{prog['total']} 완료")

    core = engine.compute(sid, "core")
    print(f"\n[1차 결과] confidence={core['confidence']}")
    for c in core["top"]:
        print(f"  {c['rank']}. {c['name']:<16} 상대 적합도 {c['total']:>5}  {c['band']}")
        for reason in c["reasons"]:
            print(f"       왜?    {reason}")
        if c["caution"]:
            print(f"       확인    {c['caution']}")
        print(f"       다음    {c['next_step']}")
    if core["tie_notice"]:
        print(f"  → {core['tie_notice']}")
    print(f"  → {core['deep_invite']}")

    deep_plan = engine.get_deep_questions(sid)
    print(f"\n[심화 분기] 클러스터 {deep_plan['clusters']} · 문항 {len(deep_plan['questions'])}개")
    for qid, val in persona["deep_answers"].items():
        engine.answer(sid, qid, val)

    deep = engine.compute(sid, "deep")
    print(f"\n[심화 결과] confidence={deep['confidence']}")
    for c in deep["top"]:
        print(f"  {c['rank']}. {c['name']:<16} 상대 적합도 {c['total']:>5}  {c['band']}")

    diff = engine.compare_stages(sid)
    print(f"\n[변화] {diff['message']}")
    if diff["moves"]:
        print(f"       {diff['moves']}")

    top_id = deep["top"][0]["job_family_id"]
    detail = engine.get_family_detail(top_id, sid)
    print(f"\n[직군 상세] {detail['name']} — {detail['one_liner']}")
    for occ in detail["occupations"][:4]:
        print(f"  · {occ['name']}   ({occ['source_label']})")
    if detail["notice"]:
        print(f"  ! {detail['notice']}")

    print(f"\n버전 {engine.versions()}")
    return 0


def cmd_demo():
    return _demo()


def cmd_offline():
    """네트워크가 죽은 상태로 전체 흐름을 돌린다. D-1 리허설에서 쓴다."""
    import types

    from p3.services import work24

    fake = types.ModuleType("requests")

    def boom(*a, **kw):
        raise ConnectionError("오프라인 리허설")

    fake.get = boom
    sys.modules["requests"] = fake
    work24.WORK24_API_KEY = "rehearsal"
    work24.work24_enabled = lambda: True

    print("=== 네트워크 차단 상태로 데모 ===\n")
    return _demo()


def cmd_check():
    personas = json.loads(FIXTURES.read_text(encoding="utf-8"))["personas"]
    fails = 0
    for p in personas:
        for stage in ("core", "deep"):
            answers = dict(p["core_answers"])
            if stage == "deep":
                answers.update(p["deep_answers"])
            ranked = scoring.annotate_bands(scoring.rank(profile_mod.build_profile(answers)))
            got = [r["job_family_id"] for r in ranked]
            exp = p["expected"][stage]["full_ranking"]
            ok = got == exp
            fails += 0 if ok else 1
            mark = "일치" if ok else "불일치"
            print(f"{p['id']:<9} {stage:<5} {mark}  {' '.join(got[:3])}")
        cl = branching.selected_clusters(p["core_answers"])
        if cl != p["expected_clusters"]:
            fails += 1
            print(f"{p['id']:<9} 분기  불일치  기대 {p['expected_clusters']} 실제 {cl}")
    print(f"\nP2 기준선 대조: 불일치 {fails}건")
    return 0 if fails == 0 else 1


COMMANDS = {"seed": cmd_seed, "demo": cmd_demo, "check": cmd_check, "offline": cmd_offline}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if name not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[name]())
