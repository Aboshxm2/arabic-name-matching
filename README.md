# arabic-name-matching

An [Agent Skill](https://agentskills.io) for matching Arabic personal names
between lists, such as a class roster against attendance sign-ins from
Microsoft Forms or Google Forms. It installs as a plugin in Claude Code,
Codex, GitHub Copilot and Cursor, and as a skill in Gemini CLI, Claude.ai,
ChatGPT and other agents.

People write their names differently on every form: with or without the
father's name, ة or ه, عبد الله or عبدالله, in Latin letters, with typos.
Judged by eye, لين and ليان or سلمى and سامي pass for the same person. This
skill has the model run a deterministic matcher instead, which applies only
the matches it is sure of and leaves the doubtful ones for you to decide.

## What it does

- Links each person's submissions across files by email, student ID and name.
- Matches a roster against them, allowing for letter forms (ة/ه, ى/ي, hamza),
  diacritics, بن/بنت, word breaks, shortened names, Latin spellings such as
  "Mohammed Alharbi" or "Alguhani", Persian keyboard letters and student IDs.
- Writes a workbook, in Arabic or English, with a ✓ per file for each name on
  the roster, plus the matches to check, everyone found, and the columns read.
- Asks about doubtful pairs and keeps your answers in a decisions file, so they
  carry over to the next run.

## Install

| Agent | Install once |
|---|---|
| Claude Code | `/plugin install arabic-name-matching --marketplace Aboshxm2/arabic-name-matching` |
| Codex | `codex plugin marketplace add Aboshxm2/arabic-name-matching`, restart Codex, then install it from `/plugins` |
| GitHub Copilot CLI | `copilot plugin marketplace add Aboshxm2/arabic-name-matching`, then `copilot plugin install arabic-name-matching@arabic-name-matching` |
| Cursor | Dashboard → Plugins & MCPs → Add Marketplace → Import from Repo, with `https://github.com/Aboshxm2/arabic-name-matching` |
| Gemini CLI | `gemini skills install https://github.com/Aboshxm2/arabic-name-matching --path skills/arabic-name-matching` |
| Any agent, with GitHub CLI 2.90+ | `gh skill install Aboshxm2/arabic-name-matching arabic-name-matching` |
| OpenCode, Windsurf and others | `npx skills add Aboshxm2/arabic-name-matching` |
| Claude.ai, ChatGPT | run `python3 build.py` and upload `dist/arabic-name-matching.zip` (Claude.ai: Settings > Features, with code execution on; ChatGPT: where your workspace has skills enabled) |

From then on the skill loads by itself whenever you ask about matching names,
attendance or who is missing; you don't need to name it. In Claude Code you
can also run it directly as `/arabic-name-matching:arabic-name-matching`.

It needs Python 3 and nothing else: no packages and no network. Where the
model can't run Python, the skill tells it to say so and stop rather than
match names by eye.

## Use

Ask for what you need and attach the files, for example:

> Here's our roster and the sign-ins from the first two sessions. Who came to
> which session, who never came, and who came without being registered?

The script also runs on its own:

```sh
python3 skills/arabic-name-matching/scripts/match_names.py inspect roster.xlsx "session 1.xlsx"
python3 skills/arabic-name-matching/scripts/match_names.py match \
    --names roster.xlsx --people "session 1.xlsx" "session 2.csv" --out results.xlsx
```

`inspect` shows which columns it will read, without printing any names, and
`match --help` lists the options. To settle doubtful pairs, write a decisions
file and pass it with `--confirmations`:

```text
# "=" confirms and "!=" rejects
هيا محمد الشهري = 4500002
دانة خالد العتيبي != دانة خالد العيتبي
```

The matcher itself, `skills/arabic-name-matching/scripts/arabic_names.py`, is
a plain Python module with no dependencies that you can copy into other
projects:

```python
import arabic_names

result = arabic_names.match(["نورة الحربي"], {"4500001": ["نورة سعد الحربي"]})
result.matched["نورة الحربي"]
# Hit(person='4500001', rule='shorter', spelling='نورة سعد الحربي')
```

Its docstring and the skill's [SKILL.md](skills/arabic-name-matching/SKILL.md)
list the matching rules.

## Privacy

The script reads and writes local files only. Using the skill in Claude.ai or
ChatGPT means uploading your files to that service, and rosters and sign-ins
hold personal data, so check what your organization allows first.

## Development

```sh
python3 -m unittest discover tests   # unit tests, made-up names only
python3 build.py                     # sync the manifests, check SKILL.md, build the zip
claude plugin validate .             # check the Claude Code plugin and marketplace
```

Each agent reads its own manifest, but the fields they share (name, version,
description, author, links) live once, in the root `plugin.json`. Change them
there and run `python3 build.py`; a test fails if the others fall out of step.
Raise `version` for each release, since installs that pin a version only
update when it changes.

| File | Read by |
|---|---|
| `plugin.json` | the shared Agent Plugins manifest (Codex, Copilot, Cursor) |
| `.claude-plugin/plugin.json`, `marketplace.json` | Claude Code, GitHub Copilot |
| `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | Codex and ChatGPT |
| `.cursor-plugin/plugin.json`, `marketplace.json` | Cursor |
| `skills/arabic-name-matching/` | every agent: the skill itself |

`evals/` holds test cases for the whole skill, also with made-up data. With
Claude Code, `claude plugin eval . --allow-tools Write,Edit,Bash --scaffold`
runs them with and without the plugin; these are billed model runs.

## License

[MIT](LICENSE)
