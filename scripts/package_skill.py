"""Build the Ask First EDA skill ZIP for the Claude desktop app."""

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from zipfile import ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "ask-first-eda"
DEFAULT_OUT = ROOT / "dist" / "ask-first-eda.zip"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
YAML_NUMBER = re.compile(
    r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[-+]?[0-9]+)?"
    r"|0(?:o[0-7]+|x[0-9a-f]+)|[-+]?\.inf|\.nan",
    re.IGNORECASE,
)


def scalar_value(value, lines):
    """Read common YAML text scalars without a third-party parser."""
    block = re.fullmatch(r"([|>])([1-9][+-]?|[+-][1-9]?|)(?:\s+#.*)?", value)
    if block:
        style, modifiers = block.groups()
        indent = modifiers.strip("+-")
        chomp = modifiers.strip("123456789")
        if indent:
            prefix = " " * int(indent)
            if any(line.strip() and not line.startswith(prefix) for line in lines):
                raise ValueError("invalid block indentation")
            body = "\n".join([*(line[len(prefix):] for line in lines), ""])
        else:
            body = dedent("\n".join([*lines, ""]))
        if style == ">":
            body = re.sub(r"(?<=\S)\n(?=\S)", " ", body)
            body = re.sub(r"(?<=\S)\n(\n+)(?=\S)", r"\1", body)
        if chomp == "-":
            return body.rstrip("\n")
        if chomp == "" and body:
            return body.rstrip("\n") + "\n"
        return body

    value = " ".join([value, *(line.strip() for line in lines)]).strip()
    if value.startswith('"'):
        text, end = json.JSONDecoder().raw_decode(value)
        if re.fullmatch(r"(?:\s+#.*)?", value[end:]):
            return text
        raise ValueError("unexpected text after quoted value")
    if value.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'(?:\s+#.*)?", value)
        if match:
            return match[1].replace("''", "'")
        raise ValueError("invalid single-quoted value")

    text = re.split(r"(?:^|\s+)#", value, maxsplit=1)[0].rstrip()
    if (
        text.lower() in {"~", "null", "true", "false"}
        or YAML_NUMBER.fullmatch(text)
        or text.startswith(("[", "{", "&", "*", "!", "|", ">"))
        or re.search(r"(?:^[-?:]|:)(?:\s|$)", text)
    ):
        raise ValueError("expected a text value")
    return text


def skill_name(skill_dir):
    frontmatter = (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines()
    if not frontmatter or frontmatter[0] != "---" or "---" not in frontmatter[1:]:
        raise ValueError("SKILL.md must start with frontmatter delimited by ---")
    lines = frontmatter[1:frontmatter.index("---", 1)]
    fields = {}
    for index, line in enumerate(lines):
        match = re.fullmatch(r"(['\"]?)(name|description)\1:[ \t]*(.*)", line)
        if not match:
            continue
        _, field, value = match.groups()
        if field in fields:
            raise ValueError(f"SKILL.md has a duplicate {field}")
        continuation = []
        for following in lines[index + 1:]:
            if following and not following[0].isspace():
                break
            continuation.append(following)
        try:
            fields[field] = scalar_value(value, continuation)
        except ValueError as error:
            raise ValueError(f"SKILL.md {field}: {error}") from error

    name = fields.get("name", "")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        raise ValueError("SKILL.md name must be 1–64 lowercase letters, digits, or hyphens")
    if name != skill_dir.name:
        raise ValueError(f"SKILL.md name {name!r} must match the folder name {skill_dir.name!r}")
    description = fields.get("description", "")
    if not description.strip() or len(description) > 200:
        raise ValueError("SKILL.md description must be non-empty and at most 200 characters")
    return name


def skill_files(skill_dir):
    for directory in (skill_dir.parent, skill_dir):
        if directory.is_symlink():
            raise ValueError(f"Cannot package symlink: {directory}")

    files = []
    for path in skill_dir.rglob("*"):
        relative = path.relative_to(skill_dir)
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Cannot package symlink: {relative}")
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if stat.S_ISDIR(mode) or path.name.endswith(".pyc"):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"Cannot package non-regular file: {relative}")
        files.append(relative.as_posix())
    return sorted(files)


def package_skill(output):
    files = {relative: SKILL_DIR / relative for relative in skill_files(SKILL_DIR)}
    name = skill_name(SKILL_DIR)
    license_path = ROOT / "LICENSE"
    if license_path.is_symlink():
        raise ValueError(f"Cannot package symlink: {license_path}")
    files["LICENSE"] = license_path
    if output.resolve().is_relative_to(SKILL_DIR):
        raise ValueError("The output ZIP must be outside the skill folder")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "skill.zip"
        with ZipFile(staged, "w") as archive:
            for relative, source in sorted(files.items()):
                entry = ZipInfo(f"{name}/{relative}", date_time=ZIP_TIMESTAMP)
                entry.create_system = 3  # Store Unix permissions on every platform.
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(entry, source.read_bytes())
        staged.replace(output)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output ZIP path (default: dist/ask-first-eda.zip)")
    output = parser.parse_args().out.absolute()
    try:
        count = package_skill(output)
    except (OSError, ValueError) as error:
        print(f"Could not package skill: {error}", file=sys.stderr)
        return 1
    print(f"Packaged {count} entries in {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
