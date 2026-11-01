---
name: arabic-name-matching
description: Match Arabic personal names between lists with a bundled, dependency-free Python script, such as a class roster against attendance or sign-in form exports (Microsoft Forms, Google Forms), a withdrawn-students list, or certificate and grade sheets. It handles spelling variants (ة/ه, ى/ي, hamza forms, diacritics, بن/بنت, عبد الله/عبدالله, Persian keyboard letters), shortened names, names typed in Latin letters, Microsoft account names and student IDs, applies only safe matches, hands doubtful pairs back for a person to confirm, and writes a workbook with attendance per file. Use it whenever someone wants to know who on a list attended or is missing, who attended without being on the list, or to reconcile or deduplicate Arabic names across spreadsheets, even if they never say "match", and use it instead of comparing Arabic names by eye.
---

# Arabic name matching

People write their names differently on every form: with or without the
father's name, ة or ه, عبد الله or عبدالله, in Latin letters, with typos. Judged
by eye, these produce confident wrong matches (لين and ليان, سلمى and سامي are
different people) and miss real ones. The bundled script applies explicit
rules, applies only the safe ones, and hands the doubtful pairs back.

Your job is to run it, check that it read the right columns, and take the user
through the decisions. Don't match names yourself, and don't report a match the
script didn't make or the user didn't confirm: a wrong match quietly credits one
person with another's attendance, while a missed one at least shows up.

## Inputs

- **The list**: the names to look for, usually a roster: `.xlsx`, `.csv`, or a
  `.txt` file with one name per line.
- **The files**: where people appear, usually one form export per session
  (`.xlsx` or `.csv`). Each row is one submission. The script links a person's
  rows across files by email, student ID and identical name, so the same person
  appearing in ten files counts as one person.

If it isn't clear which file is the list, ask. Old `.xls` files have to be saved
again as `.xlsx` or `.csv`. With no list at all, the script still links each
person's submissions and shows who appears in which file.

The script needs Python 3 and nothing else: no packages, no network. Below,
`SKILL_DIR` is the folder that holds this SKILL.md; use `python` instead of
`python3` where that is the command's name.

## 1. Check the columns

```sh
python3 SKILL_DIR/scripts/match_names.py inspect roster.xlsx "session 1.xlsx" "session 2.csv"
```

For each file this prints its sheets and the columns that could hold names,
emails or IDs, with counts of Arabic, Latin, numeric and email values (never the
values themselves). It marks the columns it will read: `name` (shown in the
results), `other name` (extra spellings, such as a name in English), `account
name` (the display name of the Microsoft account that submitted a Microsoft
Forms response), `email`, and `student ID`.

Look over the marks before matching. Common fixes, all options of `match`:

- The roster's names are on another sheet: `--names-sheet "الأعضاء"` (name or
  1-based number); check it with `inspect --sheet`.
- A wrong column was picked: `--names-column`, `--names-id-column` for the list;
  `--name-column` (repeatable), `--email-column`, `--id-column` for the files.
  Give the header, its first words, or its 1-based number, or `none` to ignore
  a column.
- Microsoft Forms' `ID` column numbers the responses; it is not a student ID,
  and the script never reads it as one.
- No student ID column, but university emails contain the ID: `--id-pattern
  '(\d{7})@'` takes it from the email. Student IDs on both sides give the
  surest matches, so use them when they exist.

## 2. Match

```sh
python3 SKILL_DIR/scripts/match_names.py match \
    --names roster.xlsx --people "session 1.xlsx" "session 2.csv" --out results.xlsx
```

Give the files in session order: each becomes a column of ✓ marks. The
workbook comes out in Arabic, right to left; add `--lang en` for English. Write
it where the user can get it (in a sandbox, the folder for output files).

The script prints a summary meant for you and writes four sheets:

- **Results** (النتائج): one row per name on the list, with its status (matched,
  check, ambiguous, not found), whom it matched and by which rule, and a ✓ for
  each file that person appears in. This is the attendance.
- **To check** (للمراجعة): possible matches that were not applied, ambiguous
  names, and people whose records carry more than one student ID.
- **People in the files** (الأشخاص في الملفات): everyone found, those who match
  no name on the list first.
- **Columns used** (الأعمدة المستخدمة): what was read from each file.

## 3. Take the user through what needs a decision

Report the counts first, then each item the user has to decide, with the
evidence the summary shows: the rule and the spelling it rests on. The rules:

| Applied automatically | |
|---|---|
| `id` | the student ID on the list matches; flagged when the names disagree |
| `confirmed` | the user confirmed it (see below) |
| `exact` | the same name once letter forms, diacritics and بن/بنت are evened out |
| `spacing` | the same letters with different word breaks |
| `shorter` | one spelling leaves names out but keeps the order, and either the given and family names agree or three names line up |
| `latin` | a Latin spelling with three names lining up, whose given name agrees with the person's Arabic spelling |

| Only suggested (status "check") | |
|---|---|
| `partial` | only two names line up, such as the given and father's names |
| `latin-partial` | the same for a Latin spelling; account names are often just given and family name |
| `typo` | one letter differs, outside the given name |

Some of these look like near-certain matches and aren't: a typo of one letter
separates real families (الشمري, الشهري), a given and father's name are shared
by cousins, and people sometimes submit a form from someone else's account.
"Ambiguous" means several people fit equally well, or the name is on the list
twice; nothing was applied. "Already matched to …" means the suggested person
went to another name by a stronger rule, which often means the list has a
duplicate.

Two pieces of evidence for the same person, such as a partial Arabic match plus
an account name with the right family name, make a strong case. It is still the
user's call, so ask rather than decide.

Write the user's answers to a decisions file and run `match` again with
`--confirmations decisions.txt`:

```text
# "=" confirms and "!=" rejects. Left: the name as it is on the list.
# Right: the person's student ID, email, or a spelling from the files.
هيا محمد الشهري = 4500002
دانة خالد العتيبي != دانة خالد العيتبي
```

Keep this file with the user's other files, so the decisions carry over when new
sessions are added. If a line doesn't point at exactly one name on the list and
one person in the files, the script stops and names the line.

## 4. Hand over

Give the user the workbook and a short summary: how many matched, who never
appears, who appears without being on the list, and what still waits for a
decision. Mention records under more than one student ID; that is usually a
typo in an ID or email, occasionally two people who share a name.

## Privacy

These files hold people's personal data. In chat, show what the user needs in
order to decide or asked to see; don't paste whole lists back unprompted, and
don't send the data anywhere else.

## If the script can't run

If Python can't be run here, say so and stop. Matching by eye is the failure
this skill exists to prevent, so don't fall back to it.
