# Ask First EDA

Ask First EDA는 데이터 파일을 읽고 질문에 대한 답을 차트와 함께 리포트에 담습니다.

[English](README.md)

## 작동 방식

```mermaid
flowchart LR
    A["파일과 질문"] --> B["데이터 검토"] --> C["지표 계산"] --> D["리포트 작성"]
```

<details>
<summary>데이터를 검토하고 지표를 계산하는 방법</summary>

Python으로 파일 구조를 확인합니다. 어떤 행을 계산에 넣을지는 사용자의 질문과 파일 내용을 보고 판단합니다.

두 기준으로 계산한 값이 다르면 두 값을 보여주고 어느 기준을 쓸지 묻습니다. 질문은 사용자의 언어로 한 번에 하나씩 합니다. 선택을 미루면 리포트에 각 값과 그 계산 기준을 함께 표시합니다.

데이터를 정제해야 할 때는 어떤 규칙을 적용할지 먼저 묻습니다. 사용자가 승인한 규칙만 복사본에 적용합니다.

분석 결과는 HTML 리포트와 JSON 요약 파일에 저장합니다. 리포트의 **요약** 탭에는 결과와 차트가, **세부** 탭에는 지표의 정의와 계산에 사용한 원본 행, 계산 과정이 나옵니다.

</details>

[예제 리포트 보기](https://ltljh.github.io/ask-first-eda/gallery/support_tickets.html) · [리포트 갤러리](https://ltljh.github.io/ask-first-eda/gallery/index.html)

![예제 리포트의 요약 탭](docs/assets/report-preview.png)

## 설치

[최신 릴리스](https://github.com/LTLJH/ask-first-eda/releases/latest)에서 ZIP 파일을 내려받으세요.

### Codex와 Claude Code

1. `ask-first-eda.zip`의 압축을 풉니다.
2. 아래 표에서 설치할 위치를 골라 스킬 폴더를 복사합니다.
3. 복사한 스킬 폴더에서 터미널을 엽니다.
4. Python 3.10 이상에서 첫 번째 명령으로 필요한 패키지를 설치합니다.
5. 두 번째 명령으로 설치 상태를 확인합니다.

| 앱 | 한 프로젝트에서 사용 | 모든 프로젝트에서 사용 |
| --- | --- | --- |
| Codex | `<project>/.agents/skills/ask-first-eda/` | `~/.agents/skills/ask-first-eda/` |
| Claude Code | `<project>/.claude/skills/ask-first-eda/` | `~/.claude/skills/ask-first-eda/` |

Windows에서도 `python` 명령을 사용하세요.

```sh
python -m pip install -r requirements.txt
python -I scripts/check_install.py
```

설치가 끝나면 프로젝트 폴더에서 Codex나 Claude Code를 실행하세요. 스킬은 이곳에 분석 작업 폴더를 만듭니다.

### Claude 데스크톱 앱

1. **Settings → Skills**를 엽니다. 버전에 따라 **Customize → Skills** 또는 **Plugins**에 있습니다.
2. `ask-first-eda.zip`을 업로드합니다.
3. Claude에게 업로드한 스킬의 `scripts/check_install.py`를 실행해 달라고 요청합니다. 앱에서 패키지 설치를 제한할 수 있습니다.

ZIP을 직접 만들려면 저장소 최상위 폴더에서 `python scripts/package_skill.py`를 실행하세요. 업로드할 파일은 `dist/ask-first-eda.zip`입니다.

로컬 설치본을 업데이트하려면 스킬 폴더를 교체하세요. 삭제하려면 그 폴더를 지우세요. 데스크톱 앱에서는 새 ZIP을 업로드하거나 앱 메뉴에서 스킬을 삭제하세요.

## 생산 일보로 시작하기

1. [예제 엑셀 파일](examples/messy_production_report/daily_report.xlsx)을 프로젝트 폴더에 복사합니다.
2. `/ask-first-eda`를 실행합니다.
3. “라인별 생산량과 가동률을 봐 줘”라고 요청합니다.

스킬이 파일을 읽고 가동률 계산에 어떤 시간을 포함할지, 어떤 정제 규칙을 적용할지 묻습니다. 결과를 보려면 `eda-work/delivery/report.html`을 여세요. 코드에서 결과를 읽으려면 같은 폴더의 `eda_summary.json`을 사용하세요.

## 지원하는 파일

CSV, TSV, 엑셀(`.xlsx`), JSON, JSONL, Parquet, 마크다운 표를 읽습니다. 예전 엑셀 파일(`.xls`)은 형식을 감지해도 내용을 읽지 못할 수 있습니다. 차트에 한글을 표시하려면 한글을 지원하는 글꼴이 필요합니다.

원본 파일은 그대로 둡니다. 모델 학습과 튜닝, 자동 가설검정, p값 계산은 지원하지 않습니다. 분석 결과만으로 인과관계를 단정하지 않습니다.

## 분석 예시

| 데이터 | 리포트와 분석 과정 |
| --- | --- |
| 고객센터 티켓 | [리포트](docs/gallery/support_tickets.html) · [시간 기준에 따른 첫 응답 준수율 차이](docs/walkthroughs/support_tickets.md#sla-clock-comparison) |
| 생산 일보 | [리포트](docs/gallery/messy_production_report.html) · [정제 과정에서 제외한 행](docs/walkthroughs/messy_production_report.md#cleaning) |
| 설비 센서 | [리포트](docs/gallery/equipment_sensors.html) · [분석 과정](docs/walkthroughs/equipment_sensors.md) |
| 배치별 스팀 사용량 | [리포트](docs/gallery/factory_utility.html) · [분석 과정](docs/walkthroughs/factory_utility.md) |
| 서울 따릉이 | [리포트](docs/gallery/seoul_bike.html) · [분석 과정](docs/walkthroughs/seoul_bike.md) |

## 평가 결과

같은 분석 모델로 합성 사례 6개를 조건별로 두 번씩 실행했습니다. 총 36회의 결과를 독립적으로 검토했습니다.

| 평가 항목 | 스킬 없이 실행 | 한 줄 지침 | Ask First EDA |
| --- | ---: | ---: | ---: |
| 계산값이 맞은 결과 | 18/24 | 24/24 | 24/24 |
| 계산 기준까지 확인해 최종값으로 제시한 결과 | 14/24 | 18/24 | 18/24 |
| 근거 없이 계산 기준을 단정한 실행 | 6/12 | 2/12 | 0/12 |

한 사례에서는 어떤 기록을 계산에 포함할지 사용자에게 물어야 했습니다. 세 조건 모두 두 번의 실행에서 이 질문을 놓쳤습니다. 한 줄 지침과 스킬은 각각 가능한 기준별로 값을 제시했습니다.

스킬을 썼을 때 분석 시간은 한 줄 지침의 1.76배, 토큰 사용량은 2.00배였습니다. 두 수치 모두 실행당 중앙값을 비교한 값입니다.

[전체 평가 결과와 채점 보정](evals/abc_summary.md) · [이전 평가](evals/ab_summary.md)

### 다음 평가

같은 생산 기록으로 한 줄 지침과 스킬을 비교할 예정입니다. 다음 세 가지를 따로 채점합니다.

- **“시간당 생산량을 알려줘.”** 설비가 멈춘 시간도 포함할지 먼저 묻는지 확인합니다.
- **“가동 시간만 기준으로 시간당 생산량을 알려줘.”** 이미 알려준 기준을 다시 묻지 않고 정확히 계산하는지 확인합니다.
- **“나중에 정할게.”** 사용자가 선택을 미루면 리포트에 전체 시간 기준 값과 가동 시간 기준 값을 구분해 표시하는지 확인합니다.

### 설치 확인 결과

| 앱 | 확인한 버전 | 2026년 11월 26일 결과 |
| --- | --- | --- |
| Claude Code | 2.1.332 | 요청에 맞는 스킬을 고르는 테스트 4개를 통과했습니다. 새 프로젝트에서 HTML 리포트와 JSON 요약 파일을 생성했습니다. |
| Codex | 0.171.0 | 같은 테스트 4개를 통과했습니다. 평가에는 `codex exec`를 사용했습니다. |
| Claude 데스크톱 앱 | 버전 기록 없음 | 직접 ZIP을 업로드해 실행을 확인했습니다. |

[설치 테스트 결과](evals/install_smoke.json) · [시스템 구조](docs/architecture.md)

## 라이선스

코드는 [MIT 라이선스](LICENSE)를 따릅니다. [예제 데이터](examples/README.md)는 각각의 라이선스를 따릅니다.

[기여 안내](CONTRIBUTING.md)
