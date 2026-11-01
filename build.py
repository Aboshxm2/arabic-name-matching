#!/usr/bin/env python3
"""Check the skill and package it.

    python3 build.py                    # check SKILL.md, write dist/arabic-name-matching.zip
    python3 build.py --install claude   # also copy it to ~/.claude/skills (Claude Code)
    python3 build.py --install codex    # or ~/.agents/skills (Codex); or give a folder

The zip and the installed copy hold only what the skill needs, SKILL.md,
scripts/ and LICENSE, in a folder named after the skill. Upload the zip in
Claude.ai (Settings > Features) or ChatGPT; both read the same Agent Skills format.
"""

import argparse
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PARTS = ("SKILL.md", "LICENSE", "scripts")
INSTALL_DIRS = {"claude": "~/.claude/skills", "codex": "~/.agents/skills"}


def check():
    """The skill's name, once its front matter passes the rules Claude and OpenAI both apply."""
    with open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit("SKILL.md: no front matter")
    fields = dict(re.findall(r"^([\w-]+): (.*)$", m.group(1), re.M))
    name, description = fields.get("name", ""), fields.get("description", "")
    problems = []
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        problems.append("name must be lowercase letters, digits and hyphens, at most 64 characters")
    if not description or len(description) > 1024:
        problems.append(f"description must be 1-1024 characters (it is {len(description)})")
    if ": " in description or " #" in description:
        problems.append('description must not contain ": " or " #", which YAML would misread')
    if problems:
        raise SystemExit("SKILL.md: " + "; ".join(problems))
    return name


def skill_files():
    """(path on disk, path inside the skill folder) for everything the skill ships."""
    for part in PARTS:
        path = os.path.join(ROOT, part)
        if os.path.isfile(path):
            yield path, part
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for f in sorted(filenames):
                if not f.endswith(".pyc"):
                    full = os.path.join(dirpath, f)
                    yield full, os.path.relpath(full, ROOT)


def package(name):
    """A zip with the skill folder at its top, the layout uploads expect."""
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    path = os.path.join(ROOT, "dist", name + ".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, rel in skill_files():
            zf.write(full, os.path.join(name, rel))
    return path


def install(name, where):
    target = os.path.join(os.path.expanduser(INSTALL_DIRS.get(where, where)), name)
    if os.path.isdir(target):
        shutil.rmtree(target)
    for full, rel in skill_files():
        dest = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(full, dest)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--install", action="append", default=[], metavar="claude|codex|DIR")
    args = parser.parse_args()
    name = check()
    print(f"package: {package(name)}")
    for where in args.install:
        print(f"installed: {install(name, where)}")


if __name__ == "__main__":
    main()
