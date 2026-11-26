# May daily production report generation spec

In the next generation session, add a `--months` argument that takes a comma-separated list of months to `examples/messy_production_report/make_data.py`, relative to the repository root. Set the default to `3,4`. When the argument is omitted, preserve the default filename, the March and April sheet order, cell values, types and formatting, and merged ranges. Generate the May file with the command below.

```sh
python3 -I examples/messy_production_report/make_data.py --months 5 --out evals/cases/production_next_month/input.xlsx
```

## May · A1:F33

The workbook has one sheet named `5월`. The first column, Row, gives the Excel row number. Merge only B4:C4 and D4:E4, writing the value shown in the table to the leftmost cell of each range. Leave blank cells empty. From row 6 onward, store numbers in columns C and E as integers and the two maintenance markers `-` as text. Store all other values, including dates and production quantities, as text exactly as shown, ignoring table padding. Subtotals and totals are fixed values.

| Row | A | B | C | D | E | F |
|---:|---|---|---|---|---|---|
| 1 | ○○공장 생산 일보 (2025년 5월) |  |  |  |  |  |
| 2 | 결재 담당 / 검토 / 승인 |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 | 일자 | A라인 |  | B라인 |  | 비고 |
| 5 |  | 생산량 | 가동시간 | 생산량 | 가동시간 |  |
| 6 | 5월 1일(목) | 12,950 kg | 20 | 11.2 t | 19 |  |
| 7 | 5월 2일(금) | 12,800 kg | 19 | 10,950 kg | 17 |  |
| 8 | 주간 소계 | 25,750 kg | 39 | 22,150 kg | 36 |  |
| 9 | 5월 5일(월) | 12,480 kg | 18 | 10,650 kg | 17 |  |
| 10 | 5월 6일(화) | 12.7 t | 19 | 10,850 kg | 18 |  |
| 11 | 5월 7일(수) | 12,350 kg | 18 | 11,050 kg | 18 |  |
| 12 | 5월 8일(목) | 12,950 kg | 20 | 11.2 t | 19 |  |
| 13 | 5월 9일(금) | 12,800 kg | 19 | 10,950 kg | 17 |  |
| 14 | 주간 소계 | 63,880 kg | 94 | 54,700 kg | 89 |  |
| 15 | 5월 12일(월) | 12,480 kg | 18 | 10,650 kg | 17 |  |
| 16 | 5월 13일(화) | - | - | 10,850 kg | 18 | A라인 정기 보전 |
| 17 | 5월 14일(수) | 12,350 kg | 18 | 11,050 kg | 18 |  |
| 18 | 5월 15일(목) | 12,950 kg | 20 | 11.2 t | 19 |  |
| 19 | 5월 16일(금) | 12,800 kg | 19 | 10,950 kg | 17 |  |
| 20 | 주간 소계 | 50,580 kg | 75 | 54,700 kg | 89 |  |
| 21 | 5월 19일(월) | 12,480 kg | 18 | 10,650 kg | 17 |  |
| 22 | 5월 20일(화) | 12.7 t | 19 | 10,850 kg | 18 |  |
| 23 | 5월 21일(수) | 12,350 kg | 18 | 0 kg | 0 | B라인 설비 고장 |
| 24 | 5월 22일(목) | 12,950 kg | 20 | 11.2 t | 19 |  |
| 25 | 5월 23일(금) | 12,800 kg | 19 | 10,950 kg | 17 |  |
| 26 | 주간 소계 | 63,280 kg | 94 | 43,650 kg | 71 |  |
| 27 | 5월 26일(월) | 12,480 kg | 18 | 10,650 kg | 17 |  |
| 28 | 5월 27일(화) | 12.7 t | 19 | 10,850 kg | 18 |  |
| 29 | 5월 28일(수) | 12,350 kg | 18 | 11,050 kg | 18 |  |
| 30 | 5월 29일(목) | 12,950 kg | 20 | 11.2 t | 19 |  |
| 31 | 5월 30일(금) | 12,800 kg | 19 | 10,950 kg | 17 |  |
| 32 | 주간 소계 | 63,280 kg | 94 | 54,700 kg | 89 |  |
| 33 | 월 합계 | 266,170 kg | 396 | 229,900 kg | 374 |  |

Include a daily report for every Monday through Friday, including public holidays. Place each week's subtotal immediately below Friday's figures. The subtotal in B14 is deliberately 600 kg above the sum of the daily rows for reconciliation. Compute the monthly total directly from the dated rows.
