# P3 백엔드·엔진 v0.2

잠재력 발견 플랫폼 MVP — 8/23 발표용 P3 담당 산출물.
작성 2026-08-19 · 이성기

**8/23 산출물**: 재현 가능한 scoring · SQLite seed · API fallback.
**협업 계약**: LLM은 adapter 경계 밖에서 점수를 만들 수 없다.

---

## 빠르게 확인하기

```bash
cd P3-백엔드엔진
pip install -r requirements.txt

python manage.py seed      # DB 생성 + P2 JSON seed (여러 번 돌려도 안전)
python manage.py check     # P2 기준선과 대조
python manage.py demo      # 진단 시작부터 직군 상세까지 전체 흐름
python manage.py offline   # 네트워크 죽은 상태로 같은 흐름 (D-1 리허설용)

python -m pytest -q        # 76 tests
```

현재 상태: **76개 테스트 통과, P2 기준선 대조 불일치 0건.**

---

## 구조

```
config.py            경로·버전·외부 연동 스위치. 비밀값은 환경변수에서만 읽는다
engine.py            P4가 호출하는 유일한 진입점

domain/              순수 함수만. DB도 네트워크도 모른다
  content.py         P2 JSON 로더 (캐시)
  profile.py         응답 → 축 점수
  branching.py       문항 노출·분기 규칙
  scoring.py         적합도·순위·밴드

db/
  schema.sql         PRD §12 ERD 그대로
  repository.py      SQL은 전부 여기에만
  seed.py            P2 JSON → SQLite (idempotent)

services/            실패해도 결과 화면을 깨뜨리지 않는 계층
  work24.py          공공데이터 API + 캐시 + 스냅샷 fallback
  explainer.py       템플릿/LLM 설명 어댑터

snapshots/
  occupations.json   API 장애 시 상세 화면을 채우는 원본 (P5가 채운다)

tests/               76 tests
manage.py            CLI
```

의존 방향은 한쪽으로만 흐른다. `engine → services → domain → content`.
도메인이 DB를 import 하지 않으므로 점수 계산은 DB 없이도 테스트된다.

---

## P4에게 — 필요한 건 engine.py 하나뿐입니다

`domain`, `db`, `services`를 직접 import 할 일이 없습니다. 반환값은 전부 평범한 dict/list라
`st.session_state`에 그대로 넣으면 됩니다.

```python
import engine

engine.bootstrap()                       # 앱 시작 시 1회
copy = engine.screen_copy()              # 화면 문구 (하드코딩 금지)

sid = engine.start_session()             # A 랜딩
engine.save_prior_test(sid, mbti="INTJ") # B 기존 진단 (점수 미반영)

for q in engine.get_core_questions():    # C 진단 질문
    engine.answer(sid, q["question_id"], 사용자입력)

engine.core_progress(sid)                # {'answered': 9, 'total': 14, 'complete': False}
result = engine.compute(sid, "core")     # E 1차 결과

plan = engine.get_deep_questions(sid)    # D 현실 조건 + 분기 문항
deep = engine.compute(sid, "deep")
diff = engine.compare_stages(sid)        # 심화 전후 변화

detail = engine.get_family_detail("J04", sid)   # F 직군 상세
engine.save_feedback(sid, "도움 됐어요")          # G 피드백
```

### compute()가 돌려주는 것

```python
{
  "top":  [3개],          # 항상 3개. 밴드가 낮아도 접히지 않는다
  "rest": [5개],          # collapsed=True인 카드가 섞여 있다
  "all":  [8개],
  "tie_notice": "이 둘은 오늘 답변으로는 거의 같은 거리예요..." 또는 None,
  "deep_invite": "여기서 끝내도 괜찮아요..." 또는 None,
  "confidence": "low" | "high",
  "versions": {...}
}
```

카드 하나에는 `name · one_liner · total · band · reasons[] · caution · next_step ·
encouragement · component_scores · collapsed`가 들어 있습니다.
접힌 카드에는 `distance_reason`이 추가로 붙습니다.

### 알아 두실 것 세 가지

- **코어 단계에는 `context` 축이 없습니다.** `change_speed`·`face_to_face` 조건이 걸린
  '확인할 점' 문구는 심화 완료 시에만 나옵니다. 없으면 `default` 문장으로 자동 대체되니
  화면에서 따로 분기할 필요는 없습니다.
- **역문항 Q05·Q06이 연속 배치되지 않게** 노출 순서를 손보실 때는 `reverse` 플래그를 보세요.
- **금지어 린트를 돌리신다면** `result_copy.json`의 `forbidden_words_exceptions`를 먼저 제거하세요.
  안 하면 팀 공식 카피 3개가 오탐으로 잡힙니다.

---

## P5에게 — 스냅샷 채우는 곳

`snapshots/occupations.json`에 8개 직군 × 34개 직업의 템플릿을 만들어 뒀습니다.
`todo_for_p5` 항목에 채울 필드를 적어 놨습니다.

이 파일이 **API 장애 시 상세 화면을 채우는 유일한 원본**입니다. 비어 있어도 직업 이름은
`job_profiles.json`에서 가져와 화면이 깨지지는 않지만, 요약과 출처 링크는 이 파일에만 있습니다.

`source_label`은 화면에 그대로 나갑니다. 출처 없이 화면에 올라가는 항목이 없도록
`test_detail_works_without_api_key`가 지키고 있습니다.

---

## 설계 결정 네 가지

### 1. API는 실패를 전제로 짰습니다

발표 중 네트워크나 API 승인 문제로 화면이 깨지는 게 가장 큰 리스크라 봤습니다.

- 키가 없으면 **호출조차 하지 않고** 스냅샷만 씁니다. 이건 장애가 아니므로 오류 문구도 안 띄웁니다
- timeout 3초, 결과당 최대 1회 호출, 60초 캐시
- 어떤 예외가 나도 스냅샷으로 내려가고 `api_fetch_logs`에 상태를 남깁니다
- 인증키와 요청 원문은 로그에 저장하지 않습니다. 해시와 상태만 남깁니다

`python manage.py offline`로 네트워크가 완전히 죽은 상태의 전체 흐름을 확인할 수 있습니다.
PRD §16의 D-9 게이트(“API 장애에도 결과/상세가 정상”)와 D-1 리허설 조건을 이걸로 만족합니다.

### 2. LLM은 점수를 만들 수 없습니다

`services/explainer.py`가 경계입니다. 점수·순위·밴드는 `domain/scoring.py`에서 이미 결정된 뒤에
문구만 채웁니다. LLM에는 계산이 끝난 구조화 데이터만 넘기고, 응답 원문이나 개인 맥락은 넘기지 않습니다.

`when` 조건 평가에 **`eval`을 쓰지 않았습니다.** 문구 파일은 P2가 편집하므로,
거기에 임의 코드가 실행될 여지를 두지 않았습니다.

기본값은 비활성(`PD_LLM_ENABLED` 미설정)이라 지금은 100% 템플릿으로 돕니다.
실제 호출 코드는 키·비용 결정(PRD §19, D-7)이 끝난 뒤에 채웁니다.
두 경로의 결과가 톤에서 구분되지 않도록 P2가 템플릿 문장을 먼저 완성해 뒀습니다.

### 3. 결과는 버전과 함께 저장합니다

`recommendations` 행마다 `engine_version` · `question_version` · `job_profile_version` ·
`copy_version`을 함께 남깁니다. 가중치가 바뀌어도 과거 결과를 그대로 재현할 수 있습니다.

문항·직군 프로파일의 **원본은 항상 Git의 JSON**이고 SQLite는 그 사본입니다.
seed는 upsert라 여러 번 돌려도 같은 상태가 됩니다. 관리자 UI는 MVP 범위 밖입니다.

### 4. 1차 결과는 코어 문항만으로 냅니다

심화 응답이 이미 저장돼 있어도 `compute(stage="core")`는 코어 14문항만 씁니다.
안 그러면 "심화 전후 비교"가 성립하지 않습니다. `test_core_result_ignores_deep_answers`가 지킵니다.

---

## 구현 중 발견해서 P2와 함께 고친 것

**SJT 4문항을 모두 같은 클러스터로 답하면 심화 문항이 2개만 나왔습니다.**

P2 명세는 "어떤 경로를 타도 심화 문항 수는 4개로 동일하다"였는데, 득표 클러스터가 하나뿐이면
상위 2개를 못 고르니 후속이 2개로 줄었습니다. 그러면 **일관되게 답한 사용자가 우유부단한
사용자보다 역량 신호를 적게 남기게 되는데, 이건 거꾸로입니다.**

부족한 자리를 `questions.json`의 클러스터 정의 순서대로 채우도록 고쳤습니다.
득표 없는 클러스터를 넣는 것이라 '대조 확인' 성격이고, 완전히 결정론적입니다.
P2의 `branching_rule.single_cluster_fill`에 사유를 남겼고, **256개 분기 조합을 전수 검증**합니다.

---

## 테스트가 지키는 것

| 파일 | 지키는 계약 |
|---|---|
| `test_persona_regression.py` | P2 기준선과 순위·점수·밴드·분기가 정확히 일치 · 같은 입력은 같은 결과 |
| `test_scoring.py` | 가중치 합 1.00 · 직군 8개 · 상위 3개는 '거리가 있음'이 될 수 없음 · 동점 규칙이 전순서 |
| `test_branching_and_profile.py` | 256개 경로 전부 심화 4문항 · 역문항 뒤집힘 · 안 물어본 축은 중립 · 축별 분모가 동적 |
| `test_engine_and_fallback.py` | seed 멱등 · 버전 저장 · 재계산 안정 · **API 3종 예외에도 상세 정상** · 인증키 미유출 |

문항이나 가중치를 바꾸면 회귀 테스트가 깨집니다. 그게 목적입니다.
깨진 걸 확인하고 P2가 기준선을 갱신한 뒤에야 변경이 확정됩니다.

---

## 남은 일

- **ContextFit의 지역·연봉·경력 30% 규칙 점수가 중립 50 고정입니다.**
  P5의 직업 매핑이 확정되면 `scoring.context_fit`의 `context_rule_score`에 실제 값을 넣습니다.
  조건이 성향 결과를 과도하게 뒤집지 않도록 상한을 30%로 묶어 둔 건 PRD §10의 결정입니다.
- **Work24 XML 스키마를 실제 응답으로 확인하지 못했습니다.** `_parse_job_info`가 태그명 후보를
  여러 개 두고 찾는 방식이라 못 찾으면 그 항목을 버립니다. P5가 키를 받으면 실제 응답으로 맞춰야 합니다.
- **LLM 호출부가 비어 있습니다.** 키·비용 결정 후 `explainer._try_llm`을 채웁니다.
  프롬프트 가드는 `result_copy.json`의 `llm_guard`에 이미 있습니다.
- **병합 시**: P4의 `app.py`를 이 폴더 루트에 두고, `PD_DATA_DIR`을 단일 `data/`로 바꾸면 됩니다.
  `config.py`의 경로 상수만 고치면 나머지는 그대로 돕니다.
