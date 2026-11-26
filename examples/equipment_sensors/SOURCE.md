# Data source

Synthetic, MIT

These data simulate pump and motor conditions in a fictional plant. They use no real companies, people, or external measurements. With the fixed seed `20250901`, `make_data.py` generates current, vibration, temperature, run commands, and shift labels for each machine at 5-minute intervals in Korea Standard Time and saves them to `sensor_readings.parquet`.

The simulation includes plant closures and planned maintenance shutdowns, missing run commands during shutdowns, current fluctuations and vibration spikes during operation, a sustained rise in vibration, restart inrush current, missing and consecutive zero vibration readings, and a change in vibration units.
