from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

from run_case import flow_section, run_case


EXAMPLE_DIRS = sorted(path for path in (ROOT / "examples").iterdir() if path.is_dir())


@pytest.mark.parametrize("example_dir", EXAMPLE_DIRS, ids=lambda path: path.name)
def test_example_format(example_dir, capsys):
    assert flow_section(example_dir / "case.md", "B").strip()
    assert flow_section(example_dir / "domain_card.md", "B", include_shared=True).strip()

    run_case(
        case_id=example_dir.name,
        flow="B",
        condition="noskill",
        max_turns=1,
        run_id="test-examples-format",
        dry_run=True,
        case_dir=example_dir,
    )
    input_listing, = [
        line.removeprefix("Inputs: ")
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Inputs: ")
    ]
    selected_inputs = [name for name in input_listing.split(", ") if name.strip()]
    assert len(selected_inputs) == 1, selected_inputs
