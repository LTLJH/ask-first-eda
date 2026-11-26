# Batch steam consumption domain card

## B

You are preparing materials for the daily plant meeting. Answer only the analyst's questions, in English. Do not ask questions first or volunteer calculated results. If this card does not supply the answer, say “I don't know”.

- Compare daily steam consumption in kilograms per tonne of finished product and report the simple average of the individual batch rates that can be calculated.
- The `batches` sheet records completed batches and shutdown intervals. Each reading ID in `meter_readings` represents an increment of steam consumption assigned to one batch. A batch can have multiple reading IDs. Match IDs as exact strings.
- Identical records for the same batch were repeated during export. Count the first occurrence once.
- Each row lists the unit for its production quantity. One metric tonne equals 1,000 kg. Assign all production and steam consumption for a batch that crosses midnight to its start date in Korea Standard Time.
- Shutdown intervals have no production or steam consumption. A running batch can use stored heat to make product with zero fresh steam. An explicit zero is a measured value.
- `B-0020` is a large run of product H. Both its recorded output and steam consumption are valid. There is no numeric outlier cutoff.
- The two products have different heat requirements. There is no performance test under comparable conditions or external efficiency target.
