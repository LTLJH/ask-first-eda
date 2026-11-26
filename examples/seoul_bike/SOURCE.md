# Data source

- The dataset is [Seoul Bike Sharing Demand, ID 560](https://archive.ics.uci.edu/dataset/560/seoul+bike+sharing+demand) from the UCI Machine Learning Repository.
- The download URL points to the [official UCI ZIP archive](https://archive.ics.uci.edu/static/public/560/seoul+bike+sharing+demand.zip).
- Downloaded on 2026-11-22 (KST).
- The dataset is licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/), as verified in the License section of the UCI dataset page.

> Easwaramoorthy, S. (2020). Seoul Bike Sharing Demand [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5F62R.

| File | Size (bytes) | SHA-256 |
|---|---:|---|
| Downloaded ZIP | 604,298 | `139e9908f0a3544bb222386855c9ce107e96467306bb8e4ce936aab59e7baac4` |
| `SeoulBikeData.csv` | 604,166 | `373339b71a8935d69e9af0abf26a70744632119862eeb3919efb389a7b749c60` |

The CSV is stored exactly as extracted from the ZIP archive. The header displays `°C` when read as either Windows-1252 or ISO-8859-1. The only non-ASCII byte in the CSV is `0xB0`, so the file cannot distinguish between the two encodings.
