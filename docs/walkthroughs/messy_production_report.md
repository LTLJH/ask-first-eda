# Messy Production Report walkthrough

This example shows how the skill follows the user’s language.

This synthetic workbook simulates factory production logs and is licensed under MIT. The conversation includes replies from a simulated user.
[Dataset provenance and license](https://github.com/LTLJH/ask-first-eda/blob/main/examples/messy_production_report/SOURCE.md)

## Step 0 — Input

| File | Size | Format |
| --- | --- | --- |
| [`daily_report.xlsx`](https://github.com/LTLJH/ask-first-eda/blob/main/examples/messy_production_report/daily_report.xlsx) | 7,427 bytes | Excel (.xlsx) |

The March sheet covers `A1:F31` and the April sheet covers `A1:F32`. The headers occupy rows 4–5 in both sheets, with merged ranges `B4:C4` and `D4:E4`. March has 21 dated records and April has 22.

## Interview

> **User (Korean):** 현장에서 쓰는 생산 일보 엑셀이에요. 라인별 생산량이랑 가동률 추이를 보고 싶어요.
>
> *Translation:* This is the daily production workbook we use on site. I'd like to see trends in production and utilization by line.

> **Analyst (Korean):** `daily_report.xlsx`의 `3월`·`4월` 시트 모두 4행에 `일자·A라인·B라인·비고`, 5행에 각 라인의 `생산량·가동시간`이 있는데, 4~5행을 두 줄짜리 머리글로 보고 6행부터 집계 대상을 확인하면 될까요?
>
> *Translation:* In both the March and April sheets of `daily_report.xlsx`, row 4 contains Date, Line A, Line B, and Notes. Row 5 contains each line’s production and operating hours. Can I treat rows 4–5 as a two-row header and look for records to aggregate starting at row 6?

> **User (Korean):** 머리글이 몇 행인지는 모르겠어요. 생산량과 가동률은 날짜가 적힌 행으로 계산해 주세요.
>
> *Translation:* I don’t know which rows contain the headers. Use the rows with dates to calculate production and utilization.

> **Analyst (Korean):** 3월 6일 A라인은 가동시간이 20으로 기록돼 있고, 하루 24시간 기준이면 가동률이 83.3%인데, 가동률의 분모는 하루 24시간으로 할까요, 아니면 일보에 없는 라인별 계획가동시간을 기준으로 할까요?
>
> *Translation:* On March 6, Line A recorded 20 operating hours, or 83.3% of a 24-hour day. Should utilization use 24 hours per day or planned operating hours by line, which the workbook does not show?

> **User (Korean):** 계획 가동시간을 기준으로 해 주세요. 하루에 라인당 20시간이고, 월별로 각 라인의 실제 가동시간 합계를 같은 달의 계획 가동시간 합계로 나눠 주세요. 쉬었던 날도 계획 가동시간에 포함해요.
>
> *Translation:* Use planned operating hours. Each line is scheduled for 20 hours a day. For each month and line, divide total actual operating hours by total planned operating hours for that month. Include idle days in planned time.

> **Analyst (Korean):** 정기 보전일인 `3월` 시트 14행(B라인)과 `4월` 시트 12행(A라인)의 `가동시간`은 `-`입니다. 두 값을 실제 가동 0시간으로 보면 월 가동률은 각각 342÷420＝81.43%, 394÷440＝89.55%인데, 두 `-`를 모두 실제 가동 0시간으로 계산하면 될까요?
>
> *Translation:* On the scheduled maintenance days, the operating hours are marked `-` on March row 14 (Line B) and April row 12 (Line A). Counting these as zero gives monthly utilization of 342 ÷ 420 = 81.43% and 394 ÷ 440 = 89.55%, respectively. Should I count both dashes as zero actual operating hours?

> **User (Korean):** 네, 두 경우 모두 실제 가동시간은 0시간으로 계산해 주세요.
>
> *Translation:* Yes, count zero actual operating hours in both cases.

> **Analyst (Korean):** 같은 정기 보전일의 `생산량`도 두 곳 모두 `-`로 기록돼 있는데, `3월` 시트 D14(B라인)와 `4월` 시트 B12(A라인)를 실제 생산량 0 kg으로 기록할까요, 아니면 생산량 미기록으로 남길까요?
>
> *Translation:* Production on those maintenance days is also marked `-`. Should I record 0 kg of actual production in March D14 (Line B) and April B12 (Line A), or leave production unrecorded?

> **User (Korean):** 두 곳 모두 생산량은 ‘해당 없음’으로 표시하고 합산에서 빼 주세요.
>
> *Translation:* Mark production as ‘not applicable’ in both cases and leave it out of the totals.

> **Analyst (Korean):** 라인별 월 생산량과 가동률을 비교한 결과를 월간 실적 공유, 생산계획 조정, 설비 보전 검토 중 어디에 주로 쓰실 예정인가요?
>
> *Translation:* Will you mainly use the comparison of monthly production and utilization by line to share monthly results, adjust production plans, or review equipment maintenance?

> **User (Korean):** 모르겠어요.
>
> *Translation:* I don’t know.

> **Analyst (Korean):** 일보에 `kg`와 `t`가 섞여 있는데, 날짜가 적힌 행만 사용하고 보전일은 합의한 대로 처리하면서, `1 t = 1,000 kg`으로 환산해 일별 추이와 월별 생산량 합계를 kg으로 보여드려도 될까요?
>
> *Translation:* The workbook mixes `kg` and `t`. May I use only dated rows, apply the agreed maintenance rules, and convert with `1 t = 1,000 kg` to show daily trends and monthly totals in kilograms?

> **User (Korean):** 네, 날짜가 적힌 행만 사용하고 보전일은 합의한 대로 처리해 주세요. t로 적힌 값은 1,000을 곱해서 일별 추이와 월별 생산량 합계를 kg으로 보여 주세요.
>
> *Translation:* Yes, use only dated rows and treat maintenance days as agreed. Multiply values in tonnes by 1,000 and show daily trends and monthly totals in kilograms.

## Cleaning

### Source layout

Rows 1–3 contain the title, approvals, and a blank row. Date and notes flank the paired production and operating-hours columns. Weekly subtotals interrupt the dated records and the monthly total closes each sheet.

### Confirmed cleaning rules

Use dated rows, convert tonnes to kilograms at 1,000 kg per tonne, and preserve both maintenance days. In the March sheet, `D14:E14` covers Line B. In April, `B12:C12` covers Line A. In both cases, production is marked as not applicable, actual operating hours are zero, and planned operating hours stay at 20.

### Cleaning results

The [cleaned CSV](../gallery/messy_production_report/cleaned_daily_report.csv) has 43 dated rows, each with both lines, original sheet and row, and separate production status fields. The [exclusion log](../gallery/messy_production_report/excluded.csv) records 20 rows across both sheets: 10 title, approval, blank, and header rows, eight weekly subtotals, and two monthly totals. The [cleaning script](../gallery/messy_production_report/clean.py) preserves source references. The [row audit](../gallery/messy_production_report/audit.json) passed with zero unexplained rows and zero errors.

### Subtotal check

In the March sheet, `B17` lists a weekly subtotal of 62,500 kg. The dated Line A cells `B12:B16` sum to 61,500 kg, a difference of 1,000 kg. The monthly analysis uses the daily rows, and the reconstructed monthly totals agree with the workbook.

## What the analysis did

The analyst summed production in kilograms per line and month. Monthly utilization divides total actual operating hours by 20 planned hours per dated row for each line. The utilization calculation includes all 86 line-days. The production calculation uses the 84 line-days with recorded output.

| Month | Line | Production | Actual / planned hours | Utilization |
| --- | --- | ---: | ---: | ---: |
| March | A | 258,340 kg | 394 / 420 | 93.81% |
| March | B | 211,400 kg | 342 / 420 | 81.43% |
| April | A | 264,160 kg | 394 / 440 | 89.55% |
| April | B | 237,700 kg | 379 / 440 | 86.14% |

Line A’s output rose 5,820 kg and utilization fell 4.26 percentage points. Line B’s output rose 26,300 kg and utilization rose 4.71 percentage points. Both utilization changes use the unrounded rates.

## Report

[HTML report](../gallery/messy_production_report.html) · [JSON summary](../gallery/messy_production_report.summary.json)

### Report headline

> 3월에서 4월 사이 A라인 월 생산량은 5,820 kg 늘고 가동률은 4.26%p 하락했습니다. B라인은 26,300 kg, 4.71%p 올랐습니다. daily_report.xlsx의 3월·4월 날짜 행 기준입니다.
>
> *Translation:* From March to April, Line A’s monthly production rose by 5,820 kg and utilization fell by 4.26 percentage points. Line B’s production and utilization rose by 26,300 kg and 4.71 percentage points. The calculations use dated rows from the March and April sheets of `daily_report.xlsx`.

### Chart questions

- How did monthly production change by line between March and April?
- How did monthly utilization change by line between March and April?
- How did each line’s daily production change?

## Ambiguity log

| ID | Topic | Status | Decision |
| --- | --- | --- | --- |
| <a id="a01"></a>A01 | Business process | resolved | A daily factory production log. |
| <a id="a02"></a>A02 | Decision | unresolved | Compare line trends. The intended use of the results remains open. |
| <a id="a03"></a>A03 | Rows and headers | resolved | Use dated records, one row containing both lines. |
| <a id="a04"></a>A04 | Utilization denominator | resolved | Plan 20 hours per dated row and line, including maintenance days. |
| <a id="a04b"></a>A04b | Production units | resolved | Convert tonnes to kilograms for daily and monthly results. |
| <a id="a05"></a>A05 | Time basis | resolved | Group the 2025 dated records by day and month. |
| <a id="a06"></a>A06 | Maintenance operating hours | resolved | Count both dashes as zero actual hours. |
| <a id="a07"></a>A07 | Maintenance production | resolved | Mark production as not applicable and exclude it from totals. |
| <a id="a08"></a>A08 | Join keys | not applicable | Append the two monthly sheets with the same structure. |

## Next month

This follow-on run used the synthetic May workbook from the [next-month evaluation case](https://github.com/LTLJH/ask-first-eda/blob/main/evals/cases/production_next_month/input.xlsx). The simulated user supplied the previous analysis as `eda_summary.json`.

> **User (Korean):** 5월 생산 일보 올렸어요. 지난달 분석한 자료는 옆에 `eda-work/` 폴더로 두었어요. 지난달까지 쓰던 기준 그대로, 5월에 A라인과 B라인이 각각 몇 kg 생산했고 가동률은 몇 %였는지 정리해 주세요.
>
> *Translation:* I’ve uploaded the May production report and put last month’s analysis beside it in `eda-work/`. Using the same rules as last month, tell me how many kilograms Lines A and B each produced in May and what their utilization rates were.

> **Analyst (Korean):** `input.xlsx`의 `5월` 시트 `A1:F33`을 모두 읽었습니다. 머리글은 4~5행이며, 날짜별 기록 22행과 주간 소계 5행, 월 합계 1행이 있습니다. 지난달 요약의 생산량·가동률·정기 보전·원본 대조 기준을 확인했고, 5월 21일 B라인 설비 고장 기록(`5월!D23:F23`)의 `0 kg`과 `0`시간 의미 및 계획시간 포함 여부를 차례로 확인하겠습니다.
>
> *Translation:* I read all of `A1:F33` in the May sheet of `input.xlsx`. Rows 4–5 are headers. There are 22 dated records, five weekly subtotals, and one monthly total. I checked last month’s rules for production, utilization, scheduled maintenance, and reconciling the source. I’ll ask what the `0 kg` and zero operating hours in the May 21 Line B equipment failure record (May `D23:F23`) mean and whether to include its planned hours.

> **User (Korean):** 네, 지난달 기준 그대로요
>
> *Translation:* Yes, use the same rules as last month.

> **Analyst (Korean):** `5월!D23`에는 5월 21일 B라인 생산량이 `0 kg`으로 적혀 있습니다. 실제 생산량 0으로 보면 22일, 해당 없음으로 보면 21일이 집계에 들어가고, 두 경우 모두 B라인 생산량 합계는 229,900 kg입니다. 5월 21일 B라인의 `0 kg`은 실제 생산량이 0이었다는 기록인가요, 아니면 정기 보전일처럼 생산량이 해당 없다는 표시인가요?
>
> *Translation:* May `D23` shows `0 kg` for Line B on May 21. Counting it as zero gives 22 production days, and treating it as not applicable gives 21. Both produce a total of 229,900 kg. Does `0 kg` mean actual zero production or that production was not applicable, as on a maintenance day?

> **User (Korean):** 그날은 설비 고장으로 B라인 생산계획을 취소했어요. 일보에는 `0 kg`으로 적었지만, 생산량은 해당 없음으로 보고 합산에서 빼 주세요.
>
> *Translation:* We canceled Line B’s production that day because of an equipment failure. The workbook says `0 kg`, but treat production as not applicable and leave it out of the total.

> **Analyst (Korean):** 5월 21일 B라인 생산량은 해당 없음으로 처리해 생산량 합산에서 제외하고, `5월!E23`의 `0`은 실제 가동시간 0시간으로 집계하겠습니다. B라인의 실제 가동시간 합계는 374시간입니다.
>
> *Translation:* I’ll exclude Line B’s May 21 production as not applicable and count the `0` in May `E23` as zero actual operating hours. Line B’s actual hours total 374.

> **User (Korean):** 실제 가동시간 0시간으로 집계해 주세요.
>
> *Translation:* Count zero actual operating hours.

> **Analyst (Korean):** 5월 21일 B라인의 계획시간 20시간을 가동률 분모에 포함하면 **374 ÷ 440 = 85.00%**, 제외하면 **374 ÷ 420 = 89.05%**입니다.
>
> *Translation:* Including Line B’s 20 planned hours for May 21 gives **374 ÷ 440 = 85.00%**. Excluding them gives **374 ÷ 420 = 89.05%**.

> **User (Korean):** 5월 21일은 B라인만 계획시간 20시간을 가동률 분모에서 빼 주세요.
>
> *Translation:* For May 21, remove the 20 planned hours from the utilization denominator for Line B only.

> **Analyst (Korean):** 2025년 5월 **A라인은 266,170 kg을 생산했고 가동률은 90.00%**, **B라인은 229,900 kg을 생산했고 가동률은 89.05%**였습니다. A라인은 **396시간 ÷ 440시간**, B라인은 **374시간 ÷ 420시간**입니다. 5월 21일 B라인은 생산량 합산에서 제외하고 실제 가동은 0시간으로 집계했습니다. 일별 합산값은 원본 월 합계와 일치했고, 5월 5~9일 A라인은 일별 합산이 63,280 kg으로 원본 주간 소계(`5월!B14`)보다 600 kg 적었습니다. 보고서에 원본 행 번호, 산식, 재현 코드를 담았습니다.
>
> *Translation:* In May 2025, **Line A produced 266,170 kg at 90.00% utilization** and **Line B produced 229,900 kg at 89.05% utilization**. Line A ran **396 of 440 hours** and Line B ran **374 of 420 hours**. Line B’s May 21 production was excluded and its actual operating time counted as zero. Daily totals matched the source monthly totals. Line A’s daily records for May 5–9 summed to 63,280 kg, 600 kg below the weekly subtotal (May `B14`). The report includes source rows, formulas, and reproduction code.

The May report was saved to `eda-work-2/delivery/report.html`.

### Follow-up

> **User (Korean):** 고마워요. 그런데 가동률을 일보에 적힌 날짜가 아니라 5월 달력일 전체(31일) 기준으로 다시 계산해 주세요. 나머지 기준은 그대로예요.
>
> *Translation:* Thanks. Please recalculate utilization using all 31 calendar days in May. Keep the other rules the same.

> **Analyst (Korean):** 5월 달력일 31일 기준 가동률은 **A라인 63.87%, B라인 62.33%**입니다. A라인은 396시간 ÷ 620시간, B라인은 374시간 ÷ 600시간입니다. 5월 21일 B라인 계획시간 20시간은 분모에서 제외했습니다. 일보에 기록이 없는 9일은 계획시간에 포함했고, 실제 가동시간은 일보에 기록된 시간만 합산했습니다. 생산량은 A라인 **266,170 kg**, B라인 **229,900 kg**입니다.
>
> *Translation:* Across all 31 calendar days in May, utilization was **63.87% for Line A and 62.33% for Line B**. Line A ran 396 of 620 hours and Line B ran 374 of 600 hours. Line B’s 20 planned hours for May 21 stayed out of the denominator. Planned hours included the nine days without entries, and actual hours came from the workbook. Production was **266,170 kg** for Line A and **229,900 kg** for Line B.

The recalculation was saved separately to `eda-work-2/delivery-2/report.html`, preserving the first May report.
