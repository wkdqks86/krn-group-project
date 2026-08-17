# 잠재력 발견

20~30대 취업준비생이 약 10분 동안 흥미·핵심역량·상황판단에 답하면, 8개 대분류 직군 중 지금 더 탐색해 볼 TOP 5를 보여주는 Streamlit MVP입니다.

점수는 규칙 기반으로 계산합니다. LLM은 점수를 산정하지 않으며, 나중에 설명문 생성에만 쓸 수 있습니다.

이 결과는 취업 성공 가능성이나 능력을 판정하지 않습니다. 현재 입력과 각 직군 초기 프로파일 사이의 상대적 적합도를 보여주는 탐색 가이드입니다.

발표 목표일: 2026-08-23

## 로컬에서 실행하기

Python 3.11 이상을 권장합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
pytest
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
pytest
```

브라우저에서 `http://localhost:8501` 이 열립니다.

## 시크릿 / API 키

공공데이터·LLM 키는 저장소에 올리지 마세요.

1. `.streamlit/secrets.toml.example` 을 복사해 `.streamlit/secrets.toml` 을 만듭니다.
2. 또는 `.env.example` 을 참고해 로컬 환경변수를 둡니다.

현재 Work24 실시간 엔드포인트는 비어 있습니다. 키가 없어도 직업 스냅샷으로 결과 화면이 동작합니다.

## 폴더 구조

```text
krn-group-project/
├─ app.py                  # Streamlit 화면 흐름 (A~G)
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ data/
│  ├─ questions.json       # 문항·선택지·점수 맵 v0.1
│  ├─ job_profiles.json    # 8개 직군 12축 요구 벡터·가중치
│  └─ occupations.json     # 직군별 연관 직업 스냅샷
├─ domain/
│  ├─ scoring.py           # 적합도 계산
│  └─ branching.py         # SJT 분기
├─ services/
│  ├─ work24.py            # API / 스냅샷 fallback
│  └─ explainer.py         # 템플릿 설명 (LLM 분리)
├─ docs/
│  └─ decision-log.md
└─ tests/
   └─ test_scoring.py
```

## 팀 역할 (PRD 기준)

| 역할 | 주 책임 | 이 저장소에서 주로 만지는 파일 |
| --- | --- | --- |
| P1 PM·리서치 | 범위, 시나리오, 테스트 | `docs/decision-log.md`, README |
| P2 진단·콘텐츠 | 문항, 직군 프로파일, 카피 | `data/*.json`, 결과 문구 |
| P3 백엔드·엔진 | 점수, 분기, API, 테스트 | `domain/`, `services/`, `tests/` |
| P4 프론트엔드·UX | Streamlit 화면 | `app.py` |
| P5 데이터·검증 | 직업 매핑, 라이선스, QA | `data/occupations.json`, `services/work24.py` |

문항·가중치·결과 문구를 바꿀 때는 버전과 이유를 `docs/decision-log.md` 에 남기거나 PR로 기록합니다.

## Git 협업 (GitHub Desktop)

`main`에는 직접 올리지 말고, 브랜치를 만든 뒤 Pull Request로 합칩니다.

브랜치 이름 예: `p2/questions-v0.2`, `p4/result-cards`, `p5/work24-snapshot`

### 브랜치에서 작업하기

1. 왼쪽 위에서 현재 브랜치가 `main`인지 확인합니다.
2. **Fetch origin** 으로 최신 `main`을 받습니다.
3. **Current Branch → New Branch**
4. 브랜치 이름을 넣고, Create from `main`으로 만듭니다.
5. **Publish branch** 로 원격에 올립니다.
6. 파일을 수정한 뒤 왼쪽 아래 **Summary**에 커밋 메시지를 쓰고 **Commit to [브랜치이름]**
7. **Push origin** 으로 커밋을 올립니다.

### Pull Request 만들기

1. GitHub Desktop 상단에 **Create Pull Request** 가 보이면 누릅니다. 없으면 **Branch → Create Pull Request**
2. 브라우저가 열리면 base는 `main`, compare는 방금 올린 브랜치인지 확인합니다.
3. 제목 예: `[P4] 결과 카드에 확인할 점 추가`
4. 본문에 바꾼 이유와 확인 방법을 짧게 적고 **Create pull request**
5. 리뷰 후 GitHub에서 **Merge pull request**
6. Desktop에서 `main`으로 다시 전환한 뒤 **Pull origin**

`.env`, `.venv`, `.streamlit/secrets.toml` 은 커밋하지 않습니다.

## 현재 초안의 한계

- 문항·직군 가중치는 팀 가설 v0.1 입니다. 공인 검사지를 복제하지 않았습니다.
- SQLite 저장은 아직 넣지 않았습니다. 지금은 브라우저 세션에만 남습니다.
- Work24 실시간 API는 P5가 키·엔드포인트 확정 후 연결합니다.
- LLM 설명은 꺼 두고 템플릿 문장만 사용합니다.
