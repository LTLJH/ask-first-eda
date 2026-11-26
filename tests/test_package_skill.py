import os
import re
import shutil
import subprocess
import sys
from pathlib import PurePosixPath
from zipfile import ZipFile

import pytest

from conftest import ROOT


SKILL = "ask-first-eda"
RELEASE_URL = "https://github.com/LTLJH/ask-first-eda/releases/latest"


@pytest.fixture
def package_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    script = ROOT / "scripts" / "package_skill.py"
    if script.is_file():
        shutil.copyfile(script, tmp_path / "scripts" / script.name)
    shutil.copytree(ROOT / "skills" / SKILL, tmp_path / "skills" / SKILL)
    shutil.copyfile(ROOT / "LICENSE", tmp_path / "LICENSE")
    return tmp_path


def run_packager(repo, *args):
    return subprocess.run(
        [sys.executable, "-I", repo / "scripts" / "package_skill.py", *args],
        cwd=repo.parent,
        capture_output=True,
        text=True,
    )


def test_package_contains_only_skill_files(package_repo):
    skill = package_repo / "skills" / SKILL
    for name in (
        "skills/ask-first-eda/scripts/__pycache__/cached.txt",
        "skills/ask-first-eda/scripts/stray.pyc",
        "skills/ask-first-eda/.DS_Store",
        "skills/ask-first-eda/.hidden/nested.txt",
        "skills/ask-first-eda/scripts/.hidden",
        "tests/outside.txt",
        "evals/outside.txt",
    ):
        path = package_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("exclude me", encoding="utf-8")

    result = run_packager(package_repo)
    assert result.returncode == 0, result.stderr
    output = package_repo / "dist" / f"{SKILL}.zip"
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert archive.read(f"{SKILL}/SKILL.md") == (skill / "SKILL.md").read_bytes()
        assert f"{SKILL}/scripts/check_install.py" in names
    for name in names:
        assert name.startswith(f"{SKILL}/")
        assert all(
            not part.startswith(".") and part not in {"__pycache__", "tests", "evals"}
            for part in PurePosixPath(name).parts
        )
        assert not name.endswith(".pyc")
    assert str(output) in result.stdout
    assert str(len(names)) in result.stdout


def test_package_is_reproducible_after_source_metadata_changes(package_repo):
    first = package_repo / "first.zip"
    second = package_repo / "nested" / "second.zip"
    result = run_packager(package_repo, "--out", first)
    assert result.returncode == 0, result.stderr

    source = package_repo / "skills" / SKILL / "SKILL.md"
    os.utime(source, (1_000_000_000, 1_000_000_000))
    source.chmod(0o600)
    result = run_packager(package_repo, "--out", second)
    assert result.returncode == 0, result.stderr

    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())


@pytest.mark.parametrize(
    ("name", "description", "field"),
    [
        ("another-skill", "Valid description", "name"),
        ("Ask_first_eda", "Valid description", "name"),
        ("a" * 65, "Valid description", "name"),
        pytest.param(SKILL, "a" * 201, "description", id="description-201"),
        (SKILL, '"   "', "description"),
    ],
)
def test_package_rejects_invalid_frontmatter(package_repo, name, description, field):
    source = package_repo / "skills" / SKILL / "SKILL.md"
    source.write_text(f"---\nname: {name}\ndescription: {description}\n---\n", encoding="utf-8")

    result = run_packager(package_repo)

    assert result.returncode == 1, result.stderr
    assert field in result.stderr
    assert not (package_repo / "dist" / f"{SKILL}.zip").exists()


def test_package_accepts_200_character_description(package_repo):
    source = package_repo / "skills" / SKILL / "SKILL.md"
    description = "é" * 200
    source.write_text(f"---\nname: {SKILL}\ndescription: {description}\n---\n", encoding="utf-8")

    result = run_packager(package_repo)

    assert result.returncode == 0, result.stderr


def test_package_rejects_symlinks(package_repo):
    outside = package_repo / "outside.txt"
    outside.touch()
    link = package_repo / "skills" / SKILL / "linked.txt"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"Cannot create a symlink: {error}")

    result = run_packager(package_repo)

    assert result.returncode == 1, result.stderr
    assert "symlink" in result.stderr.lower()
    assert link.name in result.stderr


def test_package_has_help():
    result = run_packager(ROOT, "--help")

    assert result.returncode == 0, result.stderr
    assert "--out" in result.stdout


def test_package_includes_repository_license(package_repo):
    result = run_packager(package_repo)

    assert result.returncode == 0, result.stderr
    with ZipFile(package_repo / "dist" / f"{SKILL}.zip") as archive:
        assert f"{SKILL}/LICENSE" in archive.namelist()
        assert archive.read(f"{SKILL}/LICENSE") == (package_repo / "LICENSE").read_bytes()


def test_package_requires_repository_license(package_repo):
    (package_repo / "LICENSE").unlink()
    result = run_packager(package_repo)

    assert result.returncode == 1, result.stderr
    assert "LICENSE" in result.stderr
    assert not (package_repo / "dist" / f"{SKILL}.zip").exists()


def test_skill_version_matches_latest_changelog_version():
    changelog = ROOT / "CHANGELOG.md"
    assert changelog.is_file()
    latest = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?(?=\s|$)", changelog.read_text(encoding="utf-8"), re.M)
    assert latest
    assert (ROOT / "skills" / SKILL / "VERSION").read_text(encoding="utf-8").strip() == latest[1]


@pytest.mark.parametrize("filename", ["README.md", "README.ko.md"])
def test_readme_documents_desktop_install(filename):
    readme = (ROOT / filename).read_text(encoding="utf-8")
    _, heading, desktop = readme.partition("### Claude desktop app\n")
    assert heading
    section = desktop.split("\n##", 1)[0]
    for term in ("python scripts/package_skill.py", "Settings", "Skills", "dist/ask-first-eda.zip", "check_install.py"):
        assert term in section
    first_step = next(line for line in section.splitlines() if line.startswith("1. "))
    assert RELEASE_URL in first_step
    assert "`ask-first-eda.zip`" in first_step
    assert "python scripts/package_skill.py" not in first_step
