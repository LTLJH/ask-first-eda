import ast
import json
import re
import shutil
import subprocess
import sys

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from conftest import ROOT, SCRIPTS
from test_skill_docs import documented_script_commands, skill_section


def test_run_case_helpers_work_without_fcntl(tmp_path):
    (tmp_path / "case.md").write_text("inputs: input.csv\n\n## B\nFlow body\n", encoding="utf-8")
    (tmp_path / "input.csv").write_text("value\n1\n", encoding="utf-8")
    script = """
from pathlib import Path
import sys

sys.modules['fcntl'] = None
sys.path.insert(0, sys.argv[1])
from run_case import case_inputs, flow_section

case = Path(sys.argv[2])
assert flow_section(case / 'case.md', 'B') == 'Flow body'
assert case_inputs(case) == [case / 'input.csv']
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, ROOT / "evals", tmp_path],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_scripts_avoid_unconditional_unix_only_imports():
    unix_only = {"fcntl", "pwd", "grp", "termios", "resource"}
    paths = [ROOT / "tests" / "conftest.py"]
    for directory in (ROOT / "evals", ROOT / "scripts", SCRIPTS):
        paths.extend(sorted(directory.glob("*.py")))

    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                modules = [alias.name for alias in statement.names]
            elif isinstance(statement, ast.ImportFrom) and statement.level == 0:
                modules = [statement.module]
            else:
                continue
            for module in modules:
                if module.split(".", 1)[0] in unix_only:
                    violations.append(f"{path.relative_to(ROOT)}:{statement.lineno}: {module}")

    assert not violations, "Unconditional Unix-only imports:\n" + "\n".join(violations)


def test_evals_replace_named_temporary_files_after_with():
    violations = []
    for path in sorted((ROOT / "evals").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for block in (node for node in ast.walk(tree) if isinstance(node, ast.With)):
            temporary_paths = {
                f"{item.optional_vars.id}.name"
                for item in block.items
                if isinstance(item.optional_vars, ast.Name)
                and isinstance(item.context_expr, ast.Call)
                and ast.unparse(item.context_expr.func).split(".")[-1] == "NamedTemporaryFile"
            }
            if not temporary_paths:
                continue

            def uses_temporary_path(expression):
                return any(ast.unparse(part) in temporary_paths for part in ast.walk(expression)
                           if isinstance(part, (ast.Name, ast.Attribute)))

            body = [node for statement in block.body for node in ast.walk(statement)]
            for node in sorted(body, key=lambda node: getattr(node, "lineno", 0)):
                if isinstance(node, ast.Assign) and uses_temporary_path(node.value):
                    temporary_paths.update(target.id for target in node.targets
                                           if isinstance(target, ast.Name))
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "replace"):
                    continue
                source = node.func.value
                if ast.unparse(node.func) in {"os.replace", "Path.replace", "pathlib.Path.replace"}:
                    source = next((kw.value for kw in node.keywords if kw.arg in {"src", "self"}),
                                  node.args[0] if node.args else None)
                if source is not None and uses_temporary_path(source):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not violations, "Replace after the temporary file's with block:\n" + "\n".join(violations)


@pytest.mark.parametrize("requirements_path", ["requirements.txt", "skills/ask-first-eda/requirements.txt"])
def test_pyarrow_minimum_version(requirements_path):
    lines = (ROOT / requirements_path).read_text(encoding="utf-8").splitlines()
    requirements = [Requirement(line) for raw in lines if (line := raw.split("#", 1)[0].strip())]
    pyarrow, = [requirement for requirement in requirements if requirement.name.lower() == "pyarrow"]
    minimum = Version("14.0.1")
    assert any(spec.operator == ">=" and Version(spec.version) >= minimum for spec in pyarrow.specifier), (
        f"{requirements_path} must require pyarrow >= {minimum}; found {pyarrow}"
    )


@pytest.mark.parametrize("requirements_path", ["requirements.txt", "skills/ask-first-eda/requirements.txt"])
def test_matplotlib_minimum_version(requirements_path):
    lines = (ROOT / requirements_path).read_text(encoding="utf-8").splitlines()
    requirements = [Requirement(line) for raw in lines if (line := raw.split("#", 1)[0].strip())]
    matplotlib, = [requirement for requirement in requirements if requirement.name.lower() == "matplotlib"]
    minimum = Version("3.9")
    assert any(spec.operator == ">=" and Version(spec.version) >= minimum for spec in matplotlib.specifier), (
        f"{requirements_path} must require matplotlib >= {minimum}; found {matplotlib}"
    )


def test_tests_use_the_current_python_interpreter():
    fixed_executable = re.compile(r"\.venv[/\\]+bin[/\\]+(?:python[\d.]*|pytest)\b")
    path_expression = re.compile(r"['\"]\s*/\s*['\"]")
    fixed_paths = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Eval tests use virtual-repository paths as fixture data and log evidence.
            if path.name == "test_eval_tools.py" and (
                "self.repo" in line or "self.assertNotIn(" in line
            ):
                continue
            if fixed_executable.search(path_expression.sub("/", line)):
                fixed_paths.append(f"{path.relative_to(ROOT)}:{number}")
    assert not fixed_paths, f"Use sys.executable for test subprocesses: {', '.join(fixed_paths)}"


@pytest.mark.parametrize("doc_path", ["SKILL.md", "references/report.md"])
def test_documented_plots_command_passes_input(doc_path):
    document = (SCRIPTS.parent / doc_path).read_text(encoding="utf-8")
    commands = [args for script, args in documented_script_commands(document) if script == "plots.py"]
    assert commands, f"No plots.py command in {doc_path}"
    for args in commands:
        assert "--input" in args, f"The plots.py command in {doc_path} needs --input"
        input_index = args.index("--input") + 1
        assert args[input_index:input_index + 1] == ["$INPUT"]


@pytest.mark.parametrize("flags", [(), ("-I",)], ids=["standard", "isolated"])
def test_skill_copy_runs_throughput_pipeline(tmp_path, flags):
    skill = tmp_path / "custom skills" / "ask-first-eda"
    shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("__pycache__"))
    source = tmp_path / "data" / "throughput.csv"
    source.parent.mkdir()
    shutil.copyfile(ROOT / "evals" / "cases" / "throughput_hourly" / "input.csv", source)
    python = sys.executable

    def run(script, *args, expect_legacy_warning=False):
        result = subprocess.run([python, *flags, "-B", skill / "scripts" / script, *args],
                                cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, f"{script} {args}: {result.stderr}"
        if expect_legacy_warning:
            assert "legacy" in result.stderr.casefold(), "Legacy report must warn on stderr"
        return result.stdout

    for script in ("inspect_data.py", "profile_data.py", "plots.py", "build_report.py"):
        assert "usage:" in run(script, "--help")

    inspection = tmp_path / "inspection.json"
    run("inspect_data.py", source, "--out", inspection)
    table = json.loads(inspection.read_text(encoding="utf-8"))["tables"][0]
    assert table["n_rows"] == 4

    profile = tmp_path / "profile.json"
    run("profile_data.py", source, "--table-id", table["id"], "--out", profile)
    assert json.loads(profile.read_text(encoding="utf-8"))["n_rows"] == 4

    plot_spec = tmp_path / "plot-spec.json"
    plot_spec.write_text(json.dumps({
        "source": {"path": str(source.relative_to(tmp_path)), "table_id": table["id"]},
        "charts": [{"id": "throughput", "type": "histogram", "column": "units_produced"}],
    }), encoding="utf-8")
    chart, = json.loads(run("plots.py", "--spec", plot_spec, "--input", source,
                            "--outdir", tmp_path / "figures"))
    assert (chart["n_used"], chart["n_excluded"]) == (4, 0)

    report_spec = tmp_path / "report-spec.json"
    report_spec.write_text(json.dumps({
        "title": "시간당 처리량",
        "language": "ko",
        "summary": "기록된 네 시간의 처리량 분포입니다.",
        "data_overview": {"datasets": [{
            "id": "throughput", "format": "csv", "read_ranges": ["throughput.csv:2–5"],
            "unread": [], "rows": table["n_rows"], "columns": table["n_cols"],
        }]},
        "ambiguity_log": [],
        "charts": [{**chart, "question": "시간별 처리량은 어떻게 분포합니까?",
                    "observation": "네 행을 사용했습니다.",
                    "domain_interpretation": "각 행은 한 시간에 해당합니다.",
                    "hypothesis": "추가 가설은 검토하지 않았습니다.",
                    "next_check": "운영 여부별로 비교합니다."}],
        "metrics": [],
        "assumptions_limitations": [],
        "reproducibility": {"filters": [], "exclusions": [], "transforms": [],
                            "sample_sizes": {"throughput": chart["n_used"]},
                            "source_locators": [], "code": ""},
    }), encoding="utf-8")
    delivery = tmp_path / "delivery"
    run("build_report.py", "--spec", report_spec, "--outdir", delivery, expect_legacy_warning=True)
    html = (delivery / "report.html").read_text(encoding="utf-8")
    for heading in ("요약", "데이터 개요", "모호성 기록", "차트", "가정과 한계", "재현 절차"):
        assert f"<h2>{heading}</h2>" in html
    assert "제외 0" in html
    assert '<img src="data:image/png;base64,' in html
    sidecar = json.loads((delivery / "eda_summary.json").read_text(encoding="utf-8"))
    assert sidecar["charts"][0]["n_excluded"] == 0


@pytest.fixture
def copied_scripts(tmp_path):
    skill = tmp_path / "custom skills" / "ask-first-eda"
    shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("__pycache__"))
    return skill / "scripts"


@pytest.fixture
def copied_csv(tmp_path):
    source = tmp_path / "throughput.csv"
    shutil.copyfile(ROOT / "evals" / "cases" / "throughput_hourly" / "input.csv", source)
    return source


def _run_isolated(tmp_path, *args):
    return subprocess.run([sys.executable, "-I", "-B", *args], cwd=tmp_path,
                          capture_output=True, text=True)


def _block_import(scripts, stub_file):
    stub = scripts / stub_file
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text('raise ImportError("blocked for test")\n', encoding="utf-8")


def _assert_dependency_error(result, *module_names):
    assert result.returncode == 2, result.stderr
    assert any(name in result.stderr for name in module_names), result.stderr
    for message in ("pip install -r", "requirements.txt", "ask the user before installing"):
        assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_check_install_runs_from_copied_skill(tmp_path, copied_scripts, monkeypatch):
    skill = copied_scripts.parent
    before = {path.relative_to(skill): path.read_bytes() for path in skill.rglob("*") if path.is_file()}
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(scratch))
    monkeypatch.setenv("MPLCONFIGDIR", str(skill / "mpl-cache"))
    result = subprocess.run(
        [sys.executable, "-I", copied_scripts / "check_install.py"], cwd=tmp_path,
        capture_output=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr
    for name in ("Python", "pandas", "matplotlib", "openpyxl", "pyarrow", "charset-normalizer"):
        assert re.search(rf"(?im)^{name}\b[^\n]*\d+\.\d+", result.stdout), result.stdout
    assert "glyph" in result.stdout.casefold()
    assert "inspect/plots/build_report OK" in result.stdout
    assert not list(scratch.iterdir())
    assert {path.relative_to(skill): path.read_bytes() for path in skill.rglob("*") if path.is_file()} == before


def test_check_install_builds_valid_artifacts_in_its_work_directory(tmp_path, copied_scripts):
    work = tmp_path / "smoke work"
    work.mkdir()
    command = """
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
work = Path(sys.argv[2])
os.environ['MPLCONFIGDIR'] = str(work / 'mpl-cache')
from check_install import run_smoke
from build_report import validate_summary
import json

run_smoke(work)
html, = work.rglob('report.html')
sidecar, = work.rglob('eda_summary.json')
assert 'data:image/png;base64,' in html.read_text(encoding='utf-8')
summary = json.loads(sidecar.read_text(encoding='utf-8'))
validate_summary(summary)
chart, = summary['charts']
dataset, = summary['datasets']
assert chart['n_used'] == dataset['rows'] > 0
assert chart['n_excluded'] == 0
"""
    result = _run_isolated(tmp_path, "-c", command, copied_scripts, work)
    assert result.returncode == 0, result.stderr


def test_check_install_reports_a_missing_dependency(tmp_path, copied_scripts):
    _block_import(copied_scripts, "pandas.py")
    result = _run_isolated(tmp_path, copied_scripts / "check_install.py")
    _assert_dependency_error(result, "pandas")


def test_check_install_has_help_even_without_dependencies(tmp_path, copied_scripts):
    _block_import(copied_scripts, "pandas.py")
    result = _run_isolated(tmp_path, copied_scripts / "check_install.py", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize(("file", "heading"), [("README.md", "Install"), ("README.ko.md", "설치")])
def test_readme_documents_install_check(file, heading):
    _, section = skill_section((ROOT / file).read_text(encoding="utf-8"), heading)
    assert re.search(r"python(?:3)?\s+(?:-I\s+)?skills/ask-first-eda/scripts/check_install\.py\b", section)


def test_skill_setup_documents_install_check():
    _, section = skill_section((SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8"), "Setup")
    assert ("check_install.py", []) in documented_script_commands(section)


@pytest.mark.parametrize("backend", ["fallback", "msvcrt"])
def test_report_lock_without_fcntl(tmp_path, copied_scripts, backend):
    command = """
from concurrent.futures import ThreadPoolExecutor
import errno
import os
from pathlib import Path
import sys
from threading import Event, Lock
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
sys.modules['fcntl'] = None
sys.modules['msvcrt'] = None
calls = []
if sys.argv[3] == 'msvcrt':
    held = Lock()

    def locking(fd, mode, length):
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert length == 1
        if mode == 0:
            calls.append('release')
            held.release()
        else:
            if not held.acquire(blocking=False):
                raise OSError(errno.EACCES, 'lock held')
            calls.append('acquire')

    sys.modules['msvcrt'] = SimpleNamespace(locking=locking, LK_UNLCK=0, LK_LOCK=1, LK_NBLCK=2)

from build_report import report_lock

directory = Path(sys.argv[2])
attempting = Event()
entered = Event()

def second_writer():
    attempting.set()
    with report_lock(directory):
        entered.set()

with ThreadPoolExecutor(max_workers=1) as workers:
    with report_lock(directory):
        future = workers.submit(second_writer)
        assert attempting.wait(5)
        assert not entered.wait(0.25), 'Concurrent writer entered a held lock'
    future.result(timeout=5)
assert entered.is_set()
if sys.argv[3] == 'msvcrt':
    assert calls == ['acquire', 'release', 'acquire', 'release'], calls
"""
    result = _run_isolated(tmp_path, "-c", command, copied_scripts, tmp_path, backend)
    assert result.returncode == 0, result.stderr


def test_fallback_report_lock_reclaims_stale_file_and_releases_on_error(tmp_path, copied_scripts):
    command = """
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
sys.modules['fcntl'] = sys.modules['msvcrt'] = None
from build_report import report_lock

directory = Path(sys.argv[2])
lock = directory / '.eda-build.exclusive.lock'
lock.touch()
os.utime(lock, (1, 1))
try:
    with report_lock(directory):
        assert lock.stat().st_mtime > 1
        raise ValueError('writer failed')
except ValueError as error:
    assert str(error) == 'writer failed'
assert not lock.exists()
with report_lock(directory):
    assert lock.is_file()
assert not lock.exists()
"""
    result = _run_isolated(tmp_path, "-c", command, copied_scripts, tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("stub_file", "script", "use_csv", "module_names"), [
    pytest.param("pandas.py", "inspect_data.py", True, ("pandas",), id="pandas-inspect"),
    pytest.param("pandas.py", "profile_data.py", True, ("pandas",), id="pandas-profile"),
    pytest.param("pandas.py", "build_report.py", False, ("pandas",), id="pandas-report"),
    pytest.param("pandas.py", "audit_clean.py", False, ("pandas",), id="pandas-audit"),
    pytest.param("charset_normalizer.py", "inspect_data.py", True, ("charset_normalizer",),
                 id="charset-normalizer"),
    pytest.param("matplotlib.py", "plots.py", False, ("matplotlib",), id="matplotlib"),
    pytest.param("PIL/__init__.py", "build_report.py", False, ("PIL", "Pillow"), id="pillow"),
])
def test_cli_reports_missing_required_dependency(
    tmp_path, copied_scripts, copied_csv, stub_file, script, use_csv, module_names,
):
    _block_import(copied_scripts, stub_file)
    argument = copied_csv if use_csv else "--help"
    result = _run_isolated(tmp_path, copied_scripts / script, argument)
    _assert_dependency_error(result, *module_names)


@pytest.mark.parametrize(("module", "example_dir", "filename"), [
    pytest.param("openpyxl", "messy_production_report", "daily_report.xlsx", id="excel"),
    pytest.param("pyarrow", "equipment_sensors", "sensor_readings.parquet", id="parquet"),
])
def test_inspect_requires_optional_dependency_only_for_its_format(
    tmp_path, copied_scripts, copied_csv, module, example_dir, filename,
):
    source = tmp_path / filename
    shutil.copyfile(ROOT / "examples" / example_dir / filename, source)
    _block_import(copied_scripts, f"{module}.py")
    inspect = copied_scripts / "inspect_data.py"

    csv_result = _run_isolated(tmp_path, inspect, copied_csv)
    assert csv_result.returncode == 0, csv_result.stderr

    result = _run_isolated(tmp_path, inspect, source)
    _assert_dependency_error(result, module)


def test_missing_dependency_reports_install_instructions(tmp_path, copied_scripts):
    command = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import eda_io; eda_io.missing_dependency('example_module')"
    )
    result = _run_isolated(tmp_path, "-c", command, copied_scripts)
    _assert_dependency_error(result, "example_module")


@pytest.mark.parametrize(("version", "exit_code"), [
    pytest.param((3, 9, 0), 2, id="python-3.9"),
    pytest.param((3, 10, 0), 0, id="python-3.10"),
])
def test_check_python_minimum_version(tmp_path, copied_scripts, version, exit_code):
    command = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        f"import eda_io; assert eda_io.check_python({version!r}) is None"
    )
    result = _run_isolated(tmp_path, "-c", command, copied_scripts)
    assert result.returncode == exit_code, result.stderr
    if exit_code == 2:
        assert "Python 3.10" in result.stderr
        assert "Traceback" not in result.stderr


@pytest.mark.parametrize("script", [
    "inspect_data.py", "profile_data.py", "plots.py", "build_report.py", "audit_clean.py",
])
def test_cli_checks_python_version_before_dependencies(tmp_path, copied_scripts, script):
    for stub_file in (
        "pandas.py", "charset_normalizer.py", "matplotlib.py", "numpy.py", "PIL/__init__.py",
    ):
        _block_import(copied_scripts, stub_file)
    command = (
        "import runpy, sys; sys.version_info = (3, 9, 0); "
        "sys.argv.pop(0); runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    result = _run_isolated(tmp_path, "-c", command, copied_scripts / script, "--help")
    assert result.returncode == 2, result.stderr
    assert "Python 3.10" in result.stderr
    assert "Traceback" not in result.stderr
