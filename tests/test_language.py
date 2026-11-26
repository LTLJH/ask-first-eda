import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile(r"[가-힣]")
BINARY_SUFFIXES = {".xlsx", ".parquet", ".png"}
ALLOWED_PATHS = (
    r"README\.ko\.md",  # Korean translation of the README.
    r"examples/messy_production_report/.*",  # Korean demo inputs and materials.
    r"docs/gallery/messy_production_report.*",  # Rendered Korean demo and exports.
    r"docs/walkthroughs/messy_production_report\.md",  # Korean demo walkthrough.
    r"evals/cases/production_next_month/.*",  # Korean evaluation case materials.
    r"skills/ask-first-eda/scripts/build_report\.py",  # Korean labels in generated reports.
    r"skills/ask-first-eda/scripts/profile_data\.py",  # Profiling support for Korean text.
    r"evals/numeric_check\.py",  # Numerical checks on Korean report content.
    r"evals/gen/check_expected\.py",  # Validation of Korean evaluation outputs.
    r"evals/install_smoke\.py",  # Smoke test for routing Korean requests.
    r"evals/install_smoke\.json",  # Korean routing prompts for the smoke test.
    r"tests/[^/]*\.py",  # Tests and fixtures that exercise Korean inputs.
)


def test_hangul_only_in_allowed_paths():
    tracked_paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    violations = []
    for raw_path in tracked_paths.split(b"\0"):
        if not raw_path:
            continue
        relative_path = os.fsdecode(raw_path)
        if any(re.fullmatch(pattern, relative_path, re.DOTALL) for pattern in ALLOWED_PATHS):
            continue

        path = ROOT / relative_path
        if path.suffix.lower() in BINARY_SUFFIXES or path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if HANGUL.search(content):
            violations.append(relative_path)

    assert not violations, "Hangul found outside the allowlist:\n" + "\n".join(violations)
