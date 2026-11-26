"""Recompute and check the equipment example's facts directly from Parquet."""

import json
from pathlib import Path
from statistics import linear_regression

import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
CADENCE = pd.Timedelta(minutes=5)
RATED_CURRENT = {"P-01": 42, "P-02": 36, "P-03": 48, "P-04": 31}
KST = "Asia/Seoul"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def intervals(timestamps):
    """Summarize consecutive samples with exclusive ends."""
    group_id = timestamps.diff().ne(CADENCE).cumsum()
    return [
        {
            "start_kst": group.iloc[0].isoformat(),
            "end_exclusive_kst": (group.iloc[-1] + CADENCE).isoformat(),
            "minutes": len(group) * 5,
        }
        for _, group in timestamps.groupby(group_id)
    ]


def recompute(path):
    table = pq.read_table(path)
    require(
        table.column_names == [
            "asset_id", "ts", "current_a", "vib_rms_mm_s", "motor_temp_c", "run_cmd", "shift",
        ] and table.schema.field("ts").type.tz == KST,
        "Unexpected schema or timestamp timezone",
    )
    data = table.to_pandas().sort_values(["asset_id", "ts"], ignore_index=True)
    require(set(data["asset_id"]) == RATED_CURRENT.keys(), "Unexpected asset IDs")
    require(set(data["run_cmd"].dropna()) <= {0, 1}, "Unexpected run_cmd value")
    rated = data["asset_id"].map(RATED_CURRENT)
    running = data["run_cmd"].eq(1) | (data["run_cmd"].isna() & data["current_a"].gt(rated * 0.2))
    hour = data["ts"].dt.hour
    shift = hour.map(lambda h: "A" if 6 <= h < 14 else "B" if 14 <= h < 22 else "C")
    require(data["shift"].eq(shift).all(), "Shifts do not match KST")

    p01 = data["asset_id"].eq("P-01")
    later = data["ts"].ge(pd.Timestamp("2025-09-20", tz=KST))
    vib = data["vib_rms_mm_s"].mask(p01 & later, data["vib_rms_mm_s"] * 25.4)
    require(data.loc[~running, "current_a"].between(0, 0.4).all(), "Current during stops")
    require(vib[~running].between(0.05, 0.15).all(), "Vibration during stops")

    grid = pd.date_range("2025-09-01", "2025-10-01", tz=KST, freq=CADENCE, inclusive="left")
    rows_by_asset = {}
    stops_by_asset = {}
    restart_samples_by_asset = {}
    for asset, group in data.groupby("asset_id", sort=True):
        require(pd.DatetimeIndex(group["ts"]).equals(grid), f"Invalid 5-minute grid for {asset}")
        active = running.loc[group.index]
        stops = intervals(group.loc[~active, "ts"])
        rows_by_asset[asset] = len(group)
        stops_by_asset[asset] = {
            "interval_count": len(stops),
            "total_minutes": sum(stop["minutes"] for stop in stops),
            "null_command_stop_samples": int((~active & group["run_cmd"].isna()).sum()),
        }

        starts = active & ~active.shift(fill_value=True)
        restarts = starts | starts.shift(fill_value=False)
        ratio = group["current_a"] / RATED_CURRENT[asset]
        require(ratio.ge(3).equals(restarts) and ratio[restarts].le(5).all(),
                f"Unexpected inrush samples for {asset}")
        restart_samples_by_asset[asset] = int(restarts.sum())

    p02 = data["asset_id"].eq("P-02")
    abnormal = p02 & running & vib.ge(4.5)
    require(data.loc[abnormal, "run_cmd"].eq(1).all() and vib[abnormal].between(5, 8).all(),
            "P-02 episodes must occur during commanded running with vibration between 5 and 8")
    p02_ratio = (data.loc[abnormal, "current_a"] / RATED_CURRENT["P-02"]).round(6)
    require(p02_ratio.between(0.8, 1.2).all()
            and p02_ratio.min() <= 0.81 and p02_ratio.max() >= 1.19,
            "P-02 episode current must fluctuate about 20% around rated current")

    p03 = data["asset_id"].eq("P-03") & running
    p03_running = data.loc[p03].assign(vib=vib[p03])
    daily = p03_running.groupby(p03_running["ts"].dt.normalize())["vib"].mean()
    trend = daily.loc["2025-09-05":"2025-09-30"]
    elapsed = (trend.index - trend.index[0]).days
    require(vib[p03].lt(4.5).all() and trend.is_monotonic_increasing,
            "P-03 trend must rise without any alarm-level samples")

    p01_running = p01 & running
    p04_running = data["asset_id"].eq("P-04") & running
    null_vib = data["vib_rms_mm_s"].isna()
    zero_vib = data["vib_rms_mm_s"].eq(0)
    require((~(null_vib | zero_vib) | p04_running).all(),
            "Missing and zero vibration must be observed during P-04 running")
    return {
        "rows_by_asset": rows_by_asset,
        "stops_by_asset": stops_by_asset,
        "restart_inrush_samples_by_asset": restart_samples_by_asset,
        "p02_abnormal_running": intervals(data.loc[abnormal, "ts"]),
        "p03_running_daily_mean": {
            "days": len(trend),
            "slope_mm_s_per_day": round(linear_regression(elapsed, trend).slope, 6),
            "sep05_mm_s": round(float(trend.iloc[0]), 6),
            "sep30_mm_s": round(float(trend.iloc[-1]), 6),
        },
        "p01_running_median_vibration": {
            "before_change_mm_s": round(float(vib[p01_running & ~later].median()), 6),
            "after_change_as_recorded": round(float(data.loc[p01_running & later,
                                                          "vib_rms_mm_s"].median()), 6),
            "after_change_corrected_mm_s": round(float(vib[p01_running & later].median()), 6),
        },
        "missing_rows": {
            "any_column": int(data.isna().any(axis=1).sum()),
            "run_cmd": int(data["run_cmd"].isna().sum()),
            "vib_rms_mm_s": int(null_vib.sum()),
        },
        "p04_missing_vibration": intervals(data.loc[null_vib, "ts"]),
        "p04_zero_vibration": intervals(data.loc[zero_vib, "ts"]),
    }


def main():
    try:
        actual = recompute(HERE / "sensor_readings.parquet")
        expected = json.loads((HERE / "expected_facts.json").read_text(encoding="utf-8"))
        for key in sorted(actual.keys() | expected.keys()):
            require(key in actual and key in expected and actual[key] == expected[key],
                    f"{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")
    except (OSError, ValueError) as error:
        raise SystemExit(f"FAIL: {error}") from error
    print(f"PASS: {len(actual)} fact groups match expected_facts.json")


if __name__ == "__main__":
    main()
