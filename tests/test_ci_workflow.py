import re

from conftest import ROOT


def workflow():
    path = ROOT / ".github/workflows/ci.yml"
    assert path.is_file(), "Missing .github/workflows/ci.yml"
    return path.read_text(encoding="utf-8")


def workflow_jobs():
    return re.split(r"(?m)^  [\w-]+:$", workflow().split("\njobs:\n", 1)[1])[1:]


def test_ci_triggers_and_permissions():
    source = workflow()
    events = re.search(r"(?m)^on:\n((?:  \w+:[ \t]*\n)+)", source)
    assert events
    assert set(re.findall(r"(?m)^  (\w+):", events[1])) == {"push", "pull_request"}
    assert re.search(r"(?m)^permissions:\n  contents: read$", source)


def test_ci_jobs():
    jobs = workflow_jobs()
    assert len(jobs) == 2
    matrix, = (job for job in jobs if "matrix:" in job)
    minimum, = (job for job in jobs if "matrix:" not in job)
    assert "runs-on: ${{ matrix.os }}" in matrix
    assert "python-version: ${{ matrix.python-version }}" in matrix
    for axis, expected in (
        ("os", {"ubuntu-latest", "macos-latest", "windows-latest"}),
        ("python-version", {"3.10", "3.13"}),
    ):
        values = re.search(rf"(?m)^        {axis}: \[([^\n]+)\]$", matrix)
        assert values
        assert {value.strip(" \t'\"") for value in values[1].split(",")} == expected
    assert re.search(r"(?m)^    runs-on: ubuntu-latest$", minimum)
    assert re.search(r"(?m)^          python-version: ['\"]3\.10['\"]$", minimum)

    for job in jobs:
        assert re.findall(r"(?m)^      - uses: (\S+)$", job) == [
            "actions/checkout@v4", "actions/setup-python@v5",
        ]
        install, = re.findall(r"(?m)^\s*(python -m pip install .+)$", job)
        assert "-r requirements.txt" in install
        assert "-r requirements-dev.txt" in install
        assert job.index(install) < job.index("python -m pytest -q")

    generate, = re.findall(r"(?m)^\s*(sed .+requirements\.txt > .+)$", minimum)
    assert "s/>=/==/g" in generate
    constraints = generate.split(" > ", 1)[1]
    assert "$RUNNER_TEMP/" in constraints
    assert f"-c {constraints}" in minimum
    assert minimum.index(generate) < minimum.index(f"-c {constraints}")


def test_ci_matrix_smokes_a_copied_skill():
    matrix, = (job for job in workflow_jobs() if "matrix:" in job)
    smoke, = (step for step in matrix.split("\n      - ") if "check_install.py" in step)
    assert "shell: python" in smoke
    assert 'TemporaryDirectory(dir=os.environ["RUNNER_TEMP"])' in smoke
    assert 'skill = Path(temporary) / "ask-first-eda"' in smoke
    assert 'copytree("skills/ask-first-eda", skill)' in smoke
    assert '[sys.executable, "-I", skill / "scripts" / "check_install.py"]' in smoke
    assert "cwd=temporary, check=True" in smoke
