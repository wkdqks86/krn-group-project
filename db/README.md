# db — SQLite 저장 계층

담당: P3 백엔드·엔진

지금 앱은 모든 상태가 `st.session_state`에만 있어서 새로고침하면 사라집니다.
PRD가 요구하는 "응답·계산 로그·직군 프로파일을 분리 저장하여 재현 가능한 데모"를 위한 계층입니다.

**아직 `app.py`에 연결하지 않았습니다.** 붙일지 말지는 P4·조장 판단이고,
이 폴더만으로도 독립적으로 돌아갑니다.

## 써 보기

```bash
python -m db.seed --check   # data/*.json 정합성만 확인 (DB 안 만듦)
python -m db.seed           # DB 생성 + seed
python -m pytest tests/test_db.py -q
```

`potential_discovery.db`는 `.gitignore`에 이미 잡혀 있어 커밋되지 않습니다.

## P4가 붙이는 법

기존 흐름을 바꾸지 않고 네 군데만 추가하면 됩니다.

```python
from db import repository as repo, seed

# 1) 앱 시작 시 한 번 (여러 번 불러도 안전)
seed.run(verbose=False)

# 2) 진단 시작할 때
st.session_state.session_id = repo.create_session("v1", ENGINE_VERSION)

# 3) 결과를 계산한 뒤
repo.save_responses(sid, st.session_state.responses)
repo.save_profile(sid, user_vector, clusters, context=st.session_state.context)
repo.save_recommendations(sid, recommendations, seed.versions())
repo.complete_session(sid)

# 4) 피드백 받을 때
repo.save_feedback(sid, rating, reason)
```

세션 하나를 통째로 되살리려면:

```python
repo.replay(session_id)
# {"session": ..., "responses": ..., "profile": ..., "recommendations": ...}
```

## 설계 원칙

**개인 식별정보를 저장하지 않습니다.** `users` 표에는 익명 UUID·동의 버전·생성시각 세 칸뿐입니다.
이름·연락처·이메일 컬럼은 아예 만들지 않았고, 테스트가 그걸 지킵니다.

**결과에 버전을 함께 남깁니다.** `recommendations` 행마다 `engine_version`·`question_version`·
`job_profile_version`이 붙습니다. P2가 가중치를 바꿔도 과거 결과가 어떤 기준으로 나왔는지 알 수 있습니다.

**원본은 항상 Git의 JSON입니다.** SQLite는 그 사본이고, `seed`는 upsert라 여러 번 돌려도
같은 상태가 됩니다. 관리자 UI는 MVP 범위 밖입니다.

**인증키는 로그에 남기지 않습니다.** `api_fetch_logs`에는 요청 해시와 상태만 들어갑니다.

## 파일

| 파일 | 내용 |
|---|---|
| `schema.sql` | PRD §12 ERD. 표 11개 |
| `repository.py` | SQL은 전부 여기에만. 도메인은 DB를 모릅니다 |
| `seed.py` | `data/*.json` → SQLite. `check()`로 정합성 먼저 확인 |
