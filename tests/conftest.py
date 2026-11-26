import json
from pathlib import Path
import sys

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ask-first-eda" / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def inputs(tmp_path):
    files = {}

    def write(name, content, encoding="utf-8"):
        path = tmp_path / name
        path.write_bytes(content.encode(encoding))
        files[name] = path

    write("plain.csv", 'name,value\n"two\nlines",1\nlast,2\n')
    write("korean.csv", "이름,수량\n가나다,3\n라마바,4\n", "cp949")
    write("bom.csv", "name,value\nA,1\n", "utf-8-sig")
    write("tab.tsv", "name\tvalue\nA\t1\n", "utf-8")
    write("semi.csv", "name;value\nb;2\nc;3\n")
    write("ragged.csv", "name,value\na,1\nb,2,extra\nc\nd,4\n")
    write("ids.csv", "id,label,value\n00123,  literal  ,\n00456,NA,0\n")
    write("no_header.csv", "1,2\n3,4\n")
    write("partial.csv", 'name,value\na,1\nb,"unclosed\nc,3\n')
    write("rows.jsonl", '{"x":1}\nbroken\n{"x":3}\n')
    write("mismatch.csv", '{"rows":[{"x":1}]}')
    write("spaced.json", json.dumps({"odd.key": [{"x": 7}]}))
    write("legacy.xls", "\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "latin-1")
    nested = {"days": [
        {"date": "2026-01-01", "orders": [
            {"id": "a1", "items": [{"qty": 1}]},
            {"id": "a2", "items": [{"qty": 2}, {"qty": 3}, {"qty": 4}]},
        ]},
        {"date": "2026-01-02", "orders": [
            {"id": "b1", "items": [{"qty": 5}]},
            {"id": "b2", "items": [{"qty": 6}]},
            {"id": "b3", "items": [{"qty": 7}]},
        ]},
    ]}
    write("nested.json", json.dumps(nested))
    write("tables.md", "# First\n\n| id | label |\n| --- | --- |\n"
          "| 001 | left \\| right |\n| 002 |\n\n# Second\n\n"
          "| name | value |\n| --- | ---: |\n| a | 1 |\n")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Item", "Units"])
    sheet.merge_cells("B1:C1")
    sheet.append(["A", "=1+1", None])
    sheet["A2"].hyperlink = "https://example.invalid/"
    workbook.create_sheet("Other").append(["Notes"])
    files["book.xlsx"] = tmp_path / "book.xlsx"
    workbook.save(files["book.xlsx"])
    workbook.close()

    files["rows.parquet"] = tmp_path / "rows.parquet"
    pq.write_table(pa.table({"id": ["00123", "00456"], "x": [1, 2]}),
                   files["rows.parquet"], row_group_size=1)
    return files
