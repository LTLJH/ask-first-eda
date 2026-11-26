"""Generate one month of fictional pump sensor readings."""

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


SEED = 20250901
KST = ZoneInfo("Asia/Seoul")
START = datetime(2025, 9, 1, tzinfo=KST)
END = datetime(2025, 10, 1, tzinfo=KST)
STEP = timedelta(minutes=5)
ROWS_PER_ASSET = (END - START) // STEP
SAMPLES_PER_DAY = timedelta(days=1) // STEP
OUTPUT = Path(__file__).with_name("sensor_readings.parquet")

# asset_id: (rated current A, normal vibration mm/s, normal temperature °C)
ASSETS = {
    "P-01": (42, 2.1, 56),
    "P-02": (36, 1.9, 53),
    "P-03": (48, 2.0, 59),
    "P-04": (31, 2.2, 51),
}

# All times are KST. Time and row ranges are [start, end), indexed from zero.
# The four asset row offsets are 0, 8640, 17280, and 25920 in asset ID order.
# Weekend stops (asset-local row ranges) and their 10-minute inrush windows:
# 09/06 22:00–09/07 06:00 [1704, 1800); 09/07 06:00–06:10 [1800, 1802)
# 09/07 22:00–09/08 06:00 [1992, 2088); 09/08 06:00–06:10 [2088, 2090)
# 09/13 22:00–09/14 06:00 [3720, 3816); 09/14 06:00–06:10 [3816, 3818)
# 09/14 22:00–09/15 06:00 [4008, 4104); 09/15 06:00–06:10 [4104, 4106)
# 09/20 22:00–09/21 06:00 [5736, 5832); 09/21 06:00–06:10 [5832, 5834)
# 09/21 22:00–09/22 06:00 [6024, 6120); 09/22 06:00–06:10 [6120, 6122)
# 09/27 22:00–09/28 06:00 [7752, 7848); 09/28 06:00–06:10 [7848, 7850)
# 09/28 22:00–09/29 06:00 [8040, 8136); 09/29 06:00–06:10 [8136, 8138)
WEEKEND_STOPS = (6, 7, 13, 14, 20, 21, 27, 28)

# Planned P-02 maintenance 09/17 10:00–11:30 [13368, 13386);
# corresponding inrush 09/17 11:30–11:40 [13386, 13388).
MAINTENANCE_STOP = ("17 10:00", "17 11:30")

# Command recording gaps (including the scheduled stops listed above):
# P-01 09/27 21:45–09/28 06:15 [7749, 7851); stopped subset [7752, 7848).
# P-04 09/13 21:30–09/14 06:30 [29634, 29742); stopped subset [29640, 29736).
MISSING_COMMAND = {
    "P-01": ("27 21:45", "28 06:15"),
    "P-04": ("13 21:30", "14 06:30"),
}

# P-02 abnormal running (global rows):
# 09/04 09:10–10:45 [9614, 9633)
# 09/12 15:20–17:20 [11992, 12016)
# 09/24 01:35–03:00 [15283, 15300)
ABNORMAL_RUNNING = (
    ("04 09:10", "04 10:45"),
    ("12 15:20", "12 17:20"),
    ("24 01:35", "24 03:00"),
)

# P-04 vibration nulls 09/10 11:15–15:45 [28647, 28701);
# consecutive zero readings 09/26 07:25–09:05 [33209, 33229).
VIBRATION_GAP = ("10 11:15", "10 15:45")
VIBRATION_ZEROS = ("26 07:25", "26 09:05")

SCHEMA = pa.schema([
    pa.field("asset_id", pa.string(), nullable=False),
    pa.field("ts", pa.timestamp("us", tz=KST.key), nullable=False),
    pa.field("current_a", pa.float64(), nullable=False),
    pa.field("vib_rms_mm_s", pa.float64()),
    pa.field("motor_temp_c", pa.float64(), nullable=False),
    pa.field("run_cmd", pa.int8()),
    pa.field("shift", pa.string(), nullable=False),
])


def sample_index(day_and_time):
    timestamp = datetime.fromisoformat(f"2025-09-{day_and_time}").replace(tzinfo=KST)
    return (timestamp - START) // STEP


def window(start, end):
    return slice(sample_index(start), sample_index(end))


def make_asset(asset, nominal, sample, timestamps, shifts, rng):
    rated, normal_vibration, normal_temp = nominal
    day = sample // SAMPLES_PER_DAY
    current = rated * (1 + rng.uniform(-0.035, 0.035, ROWS_PER_ASSET))
    vibration = normal_vibration + rng.uniform(-0.2, 0.2, ROWS_PER_ASSET)
    temperature = normal_temp + 1.5 * np.sin(2 * np.pi * sample / SAMPLES_PER_DAY)
    temperature += rng.uniform(-0.8, 0.8, ROWS_PER_ASSET)
    command = np.ones(ROWS_PER_ASSET, dtype=np.int8)
    no_command = np.zeros(ROWS_PER_ASSET, dtype=bool)
    no_vibration = np.zeros(ROWS_PER_ASSET, dtype=bool)

    stops = [window(f"{date:02d} 22:00", f"{date + 1:02d} 06:00") for date in WEEKEND_STOPS]
    if asset == "P-02":
        stops.append(window(*MAINTENANCE_STOP))
    for stop in stops:
        length = stop.stop - stop.start
        current[stop] = rng.uniform(0.02, 0.24, length)
        vibration[stop] = rng.uniform(0.075, 0.125, length)
        temperature[stop] = 24 + (normal_temp - 24) * np.exp(-np.arange(length) / 16)
        command[stop] = 0
        current[stop.stop:stop.stop + 2] = rated * rng.uniform([4.2, 3.1], [4.9, 3.8])

    if asset in MISSING_COMMAND:
        no_command[window(*MISSING_COMMAND[asset])] = True

    if asset == "P-01":
        # Recorded scale change, 09/20 00:00–10/01 00:00 [5472, 8640).
        vibration[sample_index("20 00:00"):] /= 25.4
    elif asset == "P-02":
        for start, end in ABNORMAL_RUNNING:
            episode = window(start, end)
            phase = np.arange(episode.stop - episode.start) * np.pi / 4
            current[episode] = rated * (1 + 0.2 * np.sin(phase))
            vibration[episode] = 6.5 + 1.3 * np.cos(phase) + rng.uniform(-0.15, 0.15, len(phase))
    elif asset == "P-03":
        # Gradual rise during running, 09/05 00:00–10/01 00:00 [18432, 25920).
        vibration += np.maximum(day - 4, 0) * (2.2 / 25) * command
    else:
        no_vibration[window(*VIBRATION_GAP)] = True
        vibration[window(*VIBRATION_ZEROS)] = 0.0

    return pa.Table.from_arrays([
        pa.array([asset] * ROWS_PER_ASSET, type=pa.string()),
        timestamps,
        pa.array(np.round(current, 3)),
        pa.array(np.round(vibration, 6), mask=no_vibration),
        pa.array(np.round(temperature, 2)),
        pa.array(command, mask=no_command),
        shifts,
    ], schema=SCHEMA)


def data_hash(path):
    """Hash the decoded schema and rows, independent of Parquet metadata."""
    table = pq.read_table(path).combine_chunks().replace_schema_metadata(None)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sha256(sink.getvalue()).hexdigest()


def main():
    rng = np.random.default_rng(SEED)
    sample = np.arange(ROWS_PER_ASSET)
    epoch_us = int(START.timestamp()) * 1_000_000 + sample * (STEP // timedelta(microseconds=1))
    timestamps = pa.array(epoch_us, type=SCHEMA.field("ts").type)
    hours = (sample % SAMPLES_PER_DAY) // (timedelta(hours=1) // STEP)
    shifts = pa.array(np.select([(6 <= hours) & (hours < 14), (14 <= hours) & (hours < 22)],
                                ["A", "B"], default="C"))
    table = pa.concat_tables([
        make_asset(asset, nominal, sample, timestamps, shifts, rng)
        for asset, nominal in ASSETS.items()
    ])
    pq.write_table(table, OUTPUT, row_group_size=ROWS_PER_ASSET, compression="zstd")
    print(f"{OUTPUT.name}: {table.num_rows} rows")
    print(f"Data SHA-256: {data_hash(OUTPUT)}")


if __name__ == "__main__":
    main()
