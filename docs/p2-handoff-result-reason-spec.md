# [P2 인수인계] 결과 화면 근거 문구 구체화 스펙

이 문서를 받는 사람: 지금부터 결과 화면(근거·주의 문구) 수정을 전담할 협업자.
작성 배경: 현재 결과 화면의 "왜 이 직군을 더 볼까요?" 문구가 아래처럼 직군과 무관하게 똑같은 템플릿만 축 이름만 바꿔서 반복되고 있음. 훨씬 구체적으로 바꿔야 함.

## 1. 문제 (실제 캡처 예시)

```
현재 프로파일 기준 상대 적합도  41/100
지금 가장 먼저 살펴볼 만해요

왜 이 직군을 더 볼까요?
- '자기관리·실행' 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.
- '사회형 활동 선호' 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.
- '관습형 활동 선호' 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.

무엇을 확인할까요?
- 이 직군은 '자기관리·실행' 쪽을 자주 쓰는 편이에요. 실제 업무에서 어느 정도인지 공고와 함께 확인해 보면 좋아요.
```

문장 구조가 세 줄 다 동일(`'{축 이름}' 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.`)하고, `{축 이름}`만 바뀐다. 어떤 직군이든 이 세 줄 패턴은 똑같아서, 사용자 입장에서 "이 직군만의 이유"를 전혀 못 느낌.

## 2. 원인

`services/explainer.py`의 `template_reasons()` / `template_cautions()`가 `component_scores`/`cautions` 항목에서 `item["label"]`(전역 축 이름, `domain/scoring.py`의 `AXIS_LABELS`—직군과 무관하게 고정된 12개 라벨) **하나만** 꺼내서 `copy.json`의 `reason_template`/`caution_template`에 끼워 넣는다. 아래 데이터는 이미 계산돼서 넘어오는데 그냥 버려지고 있음:

- `component_scores[i]`: `axis`, `label`, `user`(사용자 점수 0-100), `requirement`(이 직군의 요구값 0-100), `weight`(이 직군에서 그 축의 비중), `contribution`(가중 기여도)
- `cautions[i]`: 위와 동일 + `gap`(요구값-사용자값 차이)
- `recommendation["name"]`, `recommendation["description"]` — 직군 이름·한 줄 설명, 지금 결과 화면에 아예 안 씀
- `data/job_profiles.json`의 `job_families[].example_occupations`(직군당 대표 직업 3개), `environment_json`(대면 비중·팀 협업·변화 속도·정량 업무 1~5점) — explainer.py에서 전혀 안 씀

## 3. 목표(완료 기준)

같은 축(예: '자기관리·실행')이 top3에 들어도, **직군이 다르면 문장이 달라야 함**. 최소 아래 중 2개 이상을 문장에 녹일 것:

1. 그 직군의 대표 직업(`example_occupations`)이나 설명(`description`)을 인용해 "이 힘이 실제로 어디서 쓰이는지" 구체화
2. 그 축이 이 직군에서 왜 중요한지(`weight`/`contribution` 순위, 숫자를 직접 노출하지 않아도 "특히 비중이 큰 축" 정도는 표현 가능)
3. `environment_json`을 활용해 주의사항을 더 구체적으로(예: 지금은 `work_style == "개인 작업 선호"`일 때 4개 직군에만 하드코딩된 문구 하나 붙는 게 전부 — 이것도 `environment_json.face_to_face`/`team_interaction` 기반으로 직군마다 다르게 계산되도록 바꿀 것)

### Before → After 예시 (J08 서비스·운영, 자기관리·실행 축)

- Before: `'자기관리·실행' 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.`
- After (예시, 그대로 채택할 필요는 없음): `'자기관리·실행' 쪽 응답이 높았어요. 서비스·운영 직군(물류 운영 담당자, 운영 매니저 등)은 반복되는 업무를 흔들림 없이 유지하는 힘을 특히 많이 쓰는 자리예요.`

## 4. 지켜야 할 것 (절대 변경 금지)

- **점수 재계산 금지**: `domain/scoring.py`의 `fit_score`/`rank_job_families`는 건드리지 않음. 이번 작업은 이미 계산된 값을 "어떻게 문장으로 보여줄지"만 바꾸는 것.
- **함수 시그니처 유지**: `template_reasons(recommendation)`, `template_cautions(recommendation, context=None)`, `explain_recommendation(recommendation, context=None, use_llm=False)` — 파라미터·리턴 타입(`list[str]` / `dict[str, list[str]]`) 그대로.
- **톤앤보이스 금지어** (`data/copy.json`의 `forbidden_words` 참고, 반드시 재확인):
  - 결핍어: 부족, 미달, 낮음, 약함, 적합하지 않음, 불리, 안 맞음
  - 단정어: 당신은, ~형 인간, 천직, 최적, 정답
  - 예측어: 성공률, 합격 가능성, 유망, 전망 좋음
  - 과잉위로어(근거 없이 단독 사용 금지): 괜찮아요, 잘하고 있어요, 걱정 마세요
- **점수 원값 그대로 노출 금지**: `user`/`requirement`/`contribution` 같은 숫자를 "72점이라 낮아요" 식으로 직접 비교해 보여주지 말 것(예측어·결핍어 위반 소지). 순위·비중 정도의 정성적 표현만 허용.
- **LLM 미사용**: `explain_recommendation`의 `use_llm` 분기는 지금처럼 템플릿 경로만 써야 함(발표 안정성 때문에 팀이 합의한 제약). LLM 연동은 별도 안건.

## 5. 건드릴 파일

| 파일 | 할 일 |
| --- | --- |
| `services/explainer.py` | `template_reasons`/`template_cautions`가 `item["axis"]`, `recommendation["name"]`, `job_profiles.json`의 `example_occupations`/`environment_json`까지 받아서 문장을 조합하도록 확장 |
| `data/copy.json` | `reason_template`을 `{label}` 하나가 아니라 `{label}`, `{job_name}`, `{example}` 등 여러 placeholder를 받는 구조로 바꾸거나, 직군군(RIASEC 성향군)별 템플릿 묶음으로 분리 |
| `data/job_profiles.json` | 필요하면 문장 조합용 필드 추가 가능(예: 축별로 "이 직군에서 이 힘이 쓰이는 구체적 장면" 한 줄) — 스키마 바꾸면 `docs/decision-log.md`에 이유 기록 |
| `app.py` | `explain_recommendation` 호출부(결과 화면, `elif st.session_state.step == "result":` 블록)는 현재도 `recommendation` 전체(`item`)를 넘기고 있어서 구조 변경 불필요. 넘기는 값이 늘어나면 여기도 확인 |
| `tests/test_scoring.py` 및 관련 테스트 | 새 문장 조합 로직에 대한 회귀 테스트 추가 |

## 6. 검증

1. `pytest -q` 전체 통과
2. 같은 축이 2개 이상의 직군 top3에 동시에 등장하는 케이스를 만들어, 두 직군의 문장이 실제로 달라지는지 확인
3. 8개 직군 × top3 reasons + cautions 전수에 대해 금지어 스캔 스크립트 실행(0건이어야 함) — 참고: `docs/decision-log.md`의 2026-08-18 항목들에 매번 이렇게 검증한 기록 있음
4. 문장 길이·톤이 기존 화면과 어색하게 튀지 않는지 실제 Streamlit 화면에서 8개 직군 다 띄워서 눈으로 확인

## 7. 참고

- 현재 구조와 데이터 흐름 전체는 이 문서의 2절·5절 표로 충분히 파악 가능하지만, 막히면 `domain/scoring.py`의 `top_component_scores`/`caution_axes`, `services/explainer.py` 전체(60줄 남짓)를 먼저 읽을 것.
- 관련 결정 이력: `docs/decision-log.md`의 "2026-08-18 · P2 결과·화면 문구 톤앤보이스 정합" 항목(copy.json 도입 배경), "P2 연관 직업 콘텐츠 보강" 항목(같은 문제의식으로 `occupations.json`에 `fit_hint`를 추가한 선례 — 이번 작업도 비슷한 패턴으로 접근하면 됨).
