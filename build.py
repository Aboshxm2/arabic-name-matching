#!/usr/bin/env python3
"""Check the plugin, keep its manifests in step, and package the skill.

    python3 build.py                    # sync manifests, check SKILL.md, write dist/arabic-name-matching.zip
    python3 build.py --install claude   # also copy the skill to ~/.claude/skills
    python3 build.py --install codex    # or ~/.agents/skills; or give a folder

Each agent reads its own manifest (.claude-plugin, .codex-plugin, .cursor-plugin
and the marketplaces), so the fields they share live once, in the root
plugin.json: edit them there, run this, and the others follow. The zip holds
the skill alone, for uploading in Claude.ai (Settings > Features) or ChatGPT.
"""

import argparse
import json
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SHARED = ("name", "version", "description", "author", "homepage", "repository", "license", "keywords")
PLUGIN_MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json")
MARKETPLACES = (".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json", ".agents/plugins/marketplace.json")
INSTALL_DIRS = {"claude": "~/.claude/skills", "codex": "~/.agents/skills"}


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def save(path, data):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def synced_manifests():
    """{path: manifest} with the root plugin.json's shared fields copied in."""
    source = load("plugin.json")
    out = {}
    for path in PLUGIN_MANIFESTS:
        data = load(path)
        data.update({k: source[k] for k in SHARED if k in source})
        out[path] = data
    for path in MARKETPLACES:
        data = load(path)
        for entry in data["plugins"]:
            entry["name"] = source["name"]
            if "description" in entry:
                entry["description"] = source["description"]
        if "description" in data.get("metadata", {}):
            data["metadata"]["description"] = source["description"]
        out[path] = data
    return out


def stale_manifests():
    """The manifests that differ from what syncing would write."""
    return [path for path, data in synced_manifests().items() if data != load(path)]


def check():
    """The skill's folder, once its SKILL.md passes the rules Claude and OpenAI both apply."""
    name = load("plugin.json")["name"]
    skill = os.path.join(ROOT, "skills", name)
    with open(os.path.join(skill, "SKILL.md"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit("SKILL.md: no front matter")
    fields = dict(re.findall(r"^([\w-]+): (.*)$", m.group(1), re.M))
    description = fields.get("description", "")
    problems = []
    if fields.get("name") != name:
        problems.append(f"name {fields.get('name')!r} differs from the plugin's {name!r}")
    if not description or len(description) > 1024:
        problems.append(f"description must be 1-1024 characters (it is {len(description)})")
    if ": " in description or " #" in description:
        problems.append('description must not contain ": " or " #", which YAML would misread')
    if problems:
        raise SystemExit("SKILL.md: " + "; ".join(problems))
    return skill


def skill_files(skill):
    """(path on disk, path inside the skill folder) for everything the skill ships, with the licence."""
    yield os.path.join(ROOT, "LICENSE"), "LICENSE"
    for dirpath, dirnames, filenames in os.walk(skill):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for f in sorted(filenames):
            if not f.endswith(".pyc"):
                full = os.path.join(dirpath, f)
                yield full, os.path.relpath(full, skill)


def package(skill):
    """A zip with the skill folder at its top, the layout uploads expect."""
    name = os.path.basename(skill)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    path = os.path.join(ROOT, "dist", name + ".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, rel in skill_files(skill):
            zf.write(full, os.path.join(name, rel))
    return path


def install(skill, where):
    target = os.path.join(os.path.expanduser(INSTALL_DIRS.get(where, where)), os.path.basename(skill))
    if os.path.isdir(target):
        shutil.rmtree(target)
    for full, rel in skill_files(skill):
        dest = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(full, dest)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--install", action="append", default=[], metavar="claude|codex|DIR")
    args = parser.parse_args()
    for path, data in synced_manifests().items():
        save(path, data)
    skill = check()
    print(f"package: {package(skill)}")
    for where in args.install:
        print(f"installed: {install(skill, where)}")


if __name__ == "__main__":
    main()
