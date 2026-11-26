# Daily production report generation spec

Run the generator with `make_data.py --out <path>`. The default filename is `daily_report.xlsx`, with sheets `3월` and `4월` in that order. Use the fixed values below. Leave blank cells empty and store operating hours as numbers. Store other values as strings exactly as shown, including spaces and units. Subtotals and totals are fixed values.

## Top of both sheets

| Row | A | B | C | D | E | F |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ○○공장 생산 일보 (2025년 3월) | | | | | |
| 2 | 결재 담당 / 검토 / 승인 | | | | | |
| 3 | | | | | | |
| 4 | 일자 | A라인 | | B라인 | | 비고 |
| 5 | | 생산량 | 가동시간 | 생산량 | 가동시간 | |

Cell A1 on the April sheet contains `○○공장 생산 일보 (2025년 4월)`. Merge only `B4:C4` and `D4:E4` on both sheets.

## Data row rules

List Monday through Friday of each month in 2025 in date order, including public holidays that fall on those weekdays. For a line that did not run, enter `-` in both the production and operating-hour cells. Each weekly subtotal covers that week's actuals through Friday on the same sheet. If the month ends before Friday, include the remaining dates only in the monthly total. Calculate monthly totals directly from the dated rows. The only overstated cell is the Line A production subtotal for the second week of March (March 10–14), which is 1,000 kg too high.

## March data rows

| Row | A | B | C | D | E | F |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | 3월 3일(월) | 12,340 kg | 18 | 10,200 kg | 16 |  |
| 7 | 3월 4일(화) | 12.3 t | 19 | 10,500 kg | 17 |  |
| 8 | 3월 5일(수) | 11,860 kg | 18 | 10,800 kg | 18 |  |
| 9 | 3월 6일(목) | 12,600 kg | 20 | 10.9 t | 18 |  |
| 10 | 3월 7일(금) | 12,400 kg | 19 | 10,600 kg | 17 |  |
| 11 | 주간 소계 | 61,500 kg | 94 | 53,000 kg | 86 |  |
| 12 | 3월 10일(월) | 12,340 kg | 18 | 10,200 kg | 16 |  |
| 13 | 3월 11일(화) | 12.3 t | 19 | 10,500 kg | 17 |  |
| 14 | 3월 12일(수) | 11,860 kg | 18 | - | - | B라인 정기 보전 |
| 15 | 3월 13일(목) | 12,600 kg | 20 | 10.9 t | 18 |  |
| 16 | 3월 14일(금) | 12,400 kg | 19 | 10,600 kg | 17 |  |
| 17 | 주간 소계 | 62,500 kg | 94 | 42,200 kg | 68 |  |
| 18 | 3월 17일(월) | 12,340 kg | 18 | 10,200 kg | 16 |  |
| 19 | 3월 18일(화) | 12.3 t | 19 | 10,500 kg | 17 |  |
| 20 | 3월 19일(수) | 11,860 kg | 18 | 10,800 kg | 18 |  |
| 21 | 3월 20일(목) | 12,600 kg | 20 | 10.9 t | 18 |  |
| 22 | 3월 21일(금) | 12,400 kg | 19 | 10,600 kg | 17 |  |
| 23 | 주간 소계 | 61,500 kg | 94 | 53,000 kg | 86 |  |
| 24 | 3월 24일(월) | 12,340 kg | 18 | 10,200 kg | 16 |  |
| 25 | 3월 25일(화) | 12.3 t | 19 | 10,500 kg | 17 |  |
| 26 | 3월 26일(수) | 11,860 kg | 18 | 10,800 kg | 18 |  |
| 27 | 3월 27일(목) | 12,600 kg | 20 | 10.9 t | 18 |  |
| 28 | 3월 28일(금) | 12,400 kg | 19 | 10,600 kg | 17 |  |
| 29 | 주간 소계 | 61,500 kg | 94 | 53,000 kg | 86 |  |
| 30 | 3월 31일(월) | 12,340 kg | 18 | 10,200 kg | 16 |  |
| 31 | 월 합계 | 258,340 kg | 394 | 211,400 kg | 342 |  |

## April data rows

| Row | A | B | C | D | E | F |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | 4월 1일(화) | 12.6 t | 19 | 10,700 kg | 17 |  |
| 7 | 4월 2일(수) | 12,160 kg | 18 | 11,000 kg | 18 |  |
| 8 | 4월 3일(목) | 12,900 kg | 20 | 11.1 t | 18 |  |
| 9 | 4월 4일(금) | 12,700 kg | 19 | 10,800 kg | 17 |  |
| 10 | 주간 소계 | 50,360 kg | 76 | 43,600 kg | 70 |  |
| 11 | 4월 7일(월) | 12,640 kg | 18 | 10,400 kg | 16 |  |
| 12 | 4월 8일(화) | - | - | 10,700 kg | 17 | A라인 정기 보전 |
| 13 | 4월 9일(수) | 12,160 kg | 18 | 11,000 kg | 18 |  |
| 14 | 4월 10일(목) | 12,900 kg | 20 | 11.1 t | 18 |  |
| 15 | 4월 11일(금) | 12,700 kg | 19 | 10,800 kg | 17 |  |
| 16 | 주간 소계 | 50,400 kg | 75 | 54,000 kg | 86 |  |
| 17 | 4월 14일(월) | 12,640 kg | 18 | 10,400 kg | 16 |  |
| 18 | 4월 15일(화) | 12.6 t | 19 | 10,700 kg | 17 |  |
| 19 | 4월 16일(수) | 12,160 kg | 18 | 11,000 kg | 18 |  |
| 20 | 4월 17일(목) | 12,900 kg | 20 | 11.1 t | 18 |  |
| 21 | 4월 18일(금) | 12,700 kg | 19 | 10,800 kg | 17 |  |
| 22 | 주간 소계 | 63,000 kg | 94 | 54,000 kg | 86 |  |
| 23 | 4월 21일(월) | 12,640 kg | 18 | 10,400 kg | 16 |  |
| 24 | 4월 22일(화) | 12.6 t | 19 | 10,700 kg | 17 |  |
| 25 | 4월 23일(수) | 12,160 kg | 18 | 11,000 kg | 18 |  |
| 26 | 4월 24일(목) | 12,900 kg | 20 | 11.1 t | 18 |  |
| 27 | 4월 25일(금) | 12,700 kg | 19 | 10,800 kg | 17 |  |
| 28 | 주간 소계 | 63,000 kg | 94 | 54,000 kg | 86 |  |
| 29 | 4월 28일(월) | 12,640 kg | 18 | 10,400 kg | 16 |  |
| 30 | 4월 29일(화) | 12.6 t | 19 | 10,700 kg | 17 |  |
| 31 | 4월 30일(수) | 12,160 kg | 18 | 11,000 kg | 18 |  |
| 32 | 월 합계 | 264,160 kg | 394 | 237,700 kg | 379 |  |
