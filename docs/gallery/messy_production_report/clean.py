import argparse
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd


DATE_PATTERN = r"(\d+)월 (\d+)일\([월화수목금토일]\)"
MASS_PATTERN = r"([\d.,]+) (kg|t)"
SOURCE_COLUMNS = ["일자", "A라인 생산량", "A라인 가동시간", "B라인 생산량", "B라인 가동시간", "비고"]
KEYS = ["_source_sheet", "_source_row"]


def kilograms(raw):
    amount, unit = re.fullmatch(MASS_PATTERN, raw).groups()
    mass = Decimal(amount.replace(",", "")) * {"kg": 1, "t": 1000}[unit]
    return float(mass)


def compare_totals(frame, daily, sheet):
    week_rows = []
    differences = []
    for row, record in frame.iterrows():
        label = record["일자"]
        if row in daily.index:
            week_rows.append(row)
        elif label in {"주간 소계", "월 합계"}:
            details = daily.loc[week_rows] if label == "주간 소계" else daily
            for column in SOURCE_COLUMNS[1:5]:
                stated = kilograms(record[column]) if column.endswith("생산량") else int(record[column])
                observed = details[column].sum()
                if observed != stated:
                    differences.append((sheet, row, column, stated, observed, details.index.tolist()))
            week_rows = []
    return differences


def prepare(source):
    cleaned = []
    exclusions = []
    differences = []
    for sheet, frame in pd.read_excel(source, sheet_name=None, header=None, keep_default_na=False).items():
        frame.columns = SOURCE_COLUMNS
        frame.index += 1
        dates = frame["일자"].str.extract(DATE_PATTERN, expand=True)
        valid = frame["일자"].str.fullmatch(DATE_PATTERN)
        daily = frame.loc[valid].copy()
        year = int(re.search(r"(\d{4})년", frame.at[1, "일자"])[1])
        daily["일자"] = pd.to_datetime(
            {"year": year, "month": dates.loc[valid, 0].astype(int), "day": dates.loc[valid, 1].astype(int)}
        ).dt.strftime("%Y-%m-%d")
        assert daily["일자"].is_unique
        for line in ("A라인", "B라인"):
            mass_column, hours_column = f"{line} 생산량", f"{line} 가동시간"
            maintenance = daily["비고"].eq(f"{line} 정기 보전")
            assert daily[mass_column].eq("-").equals(maintenance)
            assert daily[hours_column].eq("-").equals(maintenance)
            daily[mass_column] = daily[mass_column].where(~maintenance).map(kilograms, na_action="ignore")
            daily[hours_column] = pd.to_numeric(daily[hours_column].mask(maintenance, 0))
            daily[f"{line} 생산량 상태"] = maintenance.map({True: "해당 없음", False: "기록됨"})
        differences.extend(compare_totals(frame, daily, sheet))
        daily["_source_sheet"] = sheet
        daily["_source_row"] = daily.index
        cleaned.append(daily[KEYS + list(daily.columns.drop(KEYS))])
        for row, label in frame.loc[~valid, "일자"].items():
            reason = label if label in {"주간 소계", "월 합계"} else "일자 없음 (제목·결재·빈 행·머리글)"
            exclusions.append((sheet, row, reason))
    return pd.concat(cleaned, ignore_index=True), pd.DataFrame(exclusions, columns=KEYS + ["reason"]), differences


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("cleaned", type=Path)
    parser.add_argument("excluded", type=Path)
    args = parser.parse_args()
    data, exclusions, differences = prepare(args.source)
    print("소계·합계 차이", differences)
    data.to_csv(args.cleaned, encoding="utf-8-sig", index=False)
    exclusions.to_csv(args.excluded, encoding="utf-8-sig", index=False)
