# Daily order volume fixture

Generate input.json in the separate generation session. Write one UTF-8 JSON document whose root is an array. Each row below specifies one object in array order. The first two columns are design locators and must be omitted from the file. Copy the ID and ISO date as strings and items as the ordered array of objects shown. All quantities are integers. The hand-set fixture uses no seed.

| Index | Design alias | order_id | order_date | items |
|---:|---|---|---|---|
| 0 | a1 | `"00123"` | 2026-01-01 | `[{"sku":"S1","qty":2}]` |
| 1 | a2 | `"a2"` | 2026-01-01 | `[{"sku":"S2","qty":1},{"sku":"S3","qty":2},{"sku":"S4","qty":1}]` |
| 2 | b1 | `"b1"` | 2026-01-02 | `[{"sku":"S2","qty":2}]` |
| 3 | b2 | `"b2"` | 2026-01-02 | `[{"sku":"S3","qty":1}]` |
| 4 | b3 | `"b3"` | 2026-01-02 | `[{"sku":"S1","qty":3}]` |

No nulls or duplicate order IDs. Expansion to item grain must retain each parent index and its unmodified ID. The three counting units give three different daily comparisons.
