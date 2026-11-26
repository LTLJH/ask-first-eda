# Ask First EDA

Ask First EDA는 지표의 계산 기준을 먼저 묻고, 그 기준으로 데이터를 분석해 차트가 담긴 리포트를 만듭니다.

[English](README.md)

| 시간 | 설비 상태 | 생산량(개) |
| --- | --- | ---: |
| 08:00–09:00 | 가동 | 18 |
| 09:00–10:00 | 정지 | 0 |
| 10:00–11:00 | 가동 | 22 |
| 11:00–12:00 | 가동 | 20 |

[예제 리포트 바로 보기](https://ltljh.github.io/ask-first-eda/gallery/support_tickets.html) · [갤러리 보기](https://ltljh.github.io/ask-first-eda/gallery/index.html)\
[Release에서 ZIP 받기](https://github.com/LTLJH/ask-first-eda/releases/latest)

네 시간 동안 60개를 생산했습니다. 시간당 생산량은 전체 근무 시간 기준으로 15개/h, 가동한 세 시간 기준으로 20개/h입니다.

> 시간당 생산량을 계산할 때 설비가 멈춘 한 시간도 포함할까요?

![리포트 요약 탭 예시](docs/assets/report-preview.png)

## 설치

Python 3.10 이상이 필요합니다. 압축을 푼 `ask-first-eda` 폴더에서 의존성을 설치하고 설치 상태를 점검하세요.

```sh
python -m pip install -r requirements.txt
python -I scripts/check_install.py
```

### Claude desktop app

1. [최신 Release](https://github.com/LTLJH/ask-first-eda/releases/latest)의 `ask-first-eda.zip`을 내려받아 **Settings → Skills**(또는 **Customize → Skills** / **Plugins**)에서 업로드하세요.
2. 앱에서는 패키지 설치가 막힐 수 있으므로 Claude에게 업로드한 스킬의 `scripts/check_install.py`를 실행해 사용 가능한 의존성을 확인해 달라고 요청하세요.
3. ZIP을 직접 만들려면 저장소 루트에서 `python scripts/package_skill.py`를 실행한 뒤 `dist/ask-first-eda.zip`을 업로드하세요.

### Claude Code

- 압축을 푼 폴더를 `<project>/.claude/skills/ask-first-eda/` 또는 `~/.claude/skills/ask-first-eda/`에 복사하세요(Release ZIP을 그 위치에 풀어도 됩니다).
- 터미널을 프로젝트 폴더에서 열고 Claude Code를 시작하세요. 작업 폴더가 그곳에 생깁니다.
- 한 프로젝트에만 적용하려면 프로젝트 경로를, 모든 프로젝트에 적용하려면 사용자 경로를 사용하세요.

### Codex

- 압축을 푼 폴더를 `<project>/.agents/skills/ask-first-eda/`에 복사하세요(Release ZIP을 그 위치에 풀어도 됩니다).
- 스킬을 해당 프로젝트에서 사용하려면 시작 전에 터미널을 프로젝트 폴더에서 여세요.
- 한 프로젝트에만 적용하려면 프로젝트 경로를 사용하세요.

Windows에서는 `python`을 사용하고 `python3`는 사용하지 마세요. PowerShell에서는 `Copy-Item -Recurse .\skills\ask-first-eda <project>\.claude\skills\ask-first-eda`를 사용하세요(Codex는 `.agents\skills` 경로).

업데이트는 설치된 폴더를 교체하거나 새 Release ZIP을 다시 업로드하면 됩니다. 제거는 폴더를 삭제하거나 앱에서 스킬을 삭제하세요.

| 클라이언트 | 버전 | 날짜 | 확인 범위 | 첫 실행 |
| --- | --- | --- | --- | --- |
| Claude Code | 2.1.332 | 2026-11-26 | routing 4/4(install smoke) | pass (2026-11-26, clean project, support_tickets example: eda-work/delivery/report.html and eda_summary.json created in the project folder) |
| Codex | 0.171.0 | 2026-11-26 | routing 4/4(install smoke) | covered by evaluation runs (codex exec) |
| Claude desktop app | — | 2026-11-26 | upload and run, manual | pass (manual, 2026-11-26) |

자동 확인 결과는 [설치 스모크 상태](evals/install_smoke.json)에서 확인하세요.

### 1분 안에 해보기

`examples/messy_production_report/daily_report.xlsx`를 프로젝트로 복사한 뒤 클라이언트에서 `/ask-first-eda`로 “라인별 생산량과 가동률을 봐 줘”라고 요청하세요.

예상 흐름: 한눈에 보기 → 가동률 분모 질문 → 정제 계획 확인 → 리포트.

## 리포트 예시

스킬은 사용자의 언어로 한 번에 한 가지를 묻습니다. 리포트의 요약 탭에는 분석 결과와 차트가, 세부 탭에는 근거와 계산 과정이 나옵니다.

[리포트 갤러리](docs/gallery/index.html)

- [서울 따릉이](docs/gallery/seoul_bike.html) · [분석 과정](docs/walkthroughs/seoul_bike.md)
- [배치별 스팀 사용량](docs/gallery/factory_utility.html) · [분석 과정](docs/walkthroughs/factory_utility.md)
- [고객센터 티켓 SLA](docs/gallery/support_tickets.html) · [분석 과정](docs/walkthroughs/support_tickets.md)
- [설비 센서](docs/gallery/equipment_sensors.html) · [분석 과정](docs/walkthroughs/equipment_sensors.md)
- [생산 일보](docs/gallery/messy_production_report.html) · [분석 과정](docs/walkthroughs/messy_production_report.md)

[영업시간 기준에 따른 첫 응답 준수율 차이](docs/walkthroughs/support_tickets.md#sla-clock-comparison)와 [정제 과정에서 제외한 행을 확인하는 방법](docs/walkthroughs/messy_production_report.md#cleaning)을 살펴볼 수 있습니다.

[시스템 구조](docs/architecture.md)

## 지원 입력

갤러리에는 CSV·Excel·JSONL·Parquet 예시가 있습니다.

| 입력 | 지원 범위 |
| --- | --- |
| CSV / TSV | 검사 및 분석 |
| `.xlsx` | 검사 및 분석 |
| JSON / JSONL | 검사 및 분석 |
| Parquet | 검사 및 분석 |
| Markdown 표 | 검사 및 분석 |
| `.xls` | 감지 가능; 읽기 지원은 보장하지 않음 |

차트에 한글을 표시하려면 한글을 지원하는 시스템 폰트가 필요합니다.

## 하지 않는 일

- 모델 학습 또는 튜닝
- 자동 가설검정 또는 p-value 산출
- 인과관계 주장
- 원본 파일 수정

## 평가

합성 케이스 6개를 36회 실행했습니다. 독립 검토에서 수치 정답은 기본 조건(A) 18/24, 한 줄 지침(B) 24/24, 스킬(C) 24/24였습니다.
정의까지 확인해 확정값으로 쓸 수 있었던 지표는 B와 C 모두 18/24였습니다. C에서는 근거 없이 정의를 단정하거나 홈 경로를 노출한 사례가 없었습니다.
세 조건 모두 확인이 필요한 분모를 묻지 않았습니다. C의 실행당 분석 시간과 토큰 사용량은 중앙값 기준으로 B의 약 2배였습니다. [A/B/C 결과와 채점 보정](evals/abc_summary.md)

이전 버전의 결과는 [A/B 요약](evals/ab_summary.md)에 있습니다.

## 라이선스

코드는 [MIT](LICENSE) 라이선스를 따릅니다. [예시 데이터](examples/README.md)에는 각각의 라이선스가 적용됩니다.

[기여 안내](CONTRIBUTING.md)
