"""Inspect source format, structure, values and read coverage."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eda_io import (
    UNKNOWN,
    add_table_args,
    column_info,
    emit_json,
    load_table,
    read_source,
    refuse_source_output,
)


def inspect_data(path, *, delimiter=None, header=None, encoding=None):
    source = read_source(path, delimiter=delimiter, header=header, encoding=encoding)
    if source.report.get("record_candidates"):
        source.report["warnings"].append("Select a JSON record path or candidate id to read table rows.")
    source.report["tables"] = [
        {
            "id": table.id,
            "locator": table.locator,
            "n_rows": len(table.frame),
            "n_cols": len(table.frame.columns),
            "columns": [{"name": name, **column_info(values.tolist())}
                        for name, values in table.frame.items()],
            **table.details,
        }
        for table in source.tables
    ]
    return source.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--out", type=Path, help="Write JSON to this file instead of stdout.")
    add_table_args(parser, select_table=False)
    args = parser.parse_args()
    try:
        if args.out:
            refuse_source_output(args.out, args.path)
        header = None if args.header is None else args.header == "yes"
        report = inspect_data(args.path, delimiter=args.delimiter, header=header, encoding=args.encoding)
        if args.encoding is not None and report["detected_format"] == UNKNOWN and report["encoding"] is None:
            raise ValueError(" ".join(report["warnings"]))
        emit_json(report, args.out)
    except (OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
