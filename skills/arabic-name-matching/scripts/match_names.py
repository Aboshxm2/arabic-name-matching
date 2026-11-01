#!/usr/bin/env python3
"""Find the names on a list (a roster, say) among the people in form exports.

    python3 match_names.py inspect FILE [FILE ...]
    python3 match_names.py match --names LIST --people FILE [FILE ...] [--out results.xlsx]

`inspect` shows which columns would be read from each file, without printing
any names. `match` links each person's rows across the files, matches the list
against them with arabic_names.py, prints a summary and writes a workbook.
Standard library only; ../SKILL.md describes the workflow.
"""

import argparse
import csv
import io
import os
import re
import sys
import zipfile
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arabic_names  # noqa: E402
import xlsx_lite  # noqa: E402
from arabic_names import clean, normalize  # noqa: E402

_ARABIC = re.compile(r"[ء-ي]")
_LATIN = re.compile(r"[A-Za-z]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Header starts and phrases, compared after arabic_names.normalize().
_NAME_STARTS = ("الاسم", "اسم الطالب", "اسم المتدرب", "اسم المشارك", "اسم المستفيد", "اسم الموظف")
_NAME_WORDS = ("full name", "student name", "arabic name", "english name", "name in arabic", "name in english")
_ID_STARTS = ("الرقم الجامعي", "الرقم الاكاديمي", "رقم الطالب", "رقم المتدرب", "رقم الموظف", "الرقم الوظيفي")
_ID_WORDS = ("student id", "student number", "student no", "university id", "employee id")


def unique(items):
    return list(dict.fromkeys(items))


# ---------------------------------------------------------------- reading

def read_text(path):
    """A text file's contents. Excel in Arabic locales saves CSV as Windows-1256."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1256", errors="replace")


def read_table(path, sheet=None):
    """(rows, sheet name) of a .xlsx, .csv or .txt file; rows are lists of strings.

    A .txt file is a plain list: one name per line, # starts a comment.
    """
    if not os.path.isfile(path):
        raise SystemExit(f"{path}: file not found")
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            sheets = xlsx_lite.sheet_names(path)
            if sheet is None:
                index = 0
            elif sheet in sheets:
                index = sheets.index(sheet)
            elif sheet.isdigit() and 1 <= int(sheet) <= len(sheets):
                index = int(sheet) - 1
            else:
                raise SystemExit(f"{path}: no sheet {sheet!r}; its sheets are {sheets}")
            return xlsx_lite.read_sheet(path, index), sheets[index]
        except (zipfile.BadZipFile, KeyError, IndexError, ValueError, ElementTree.ParseError) as e:
            raise SystemExit(f"{path}: can't read this workbook ({e}); save it again as .xlsx or .csv")
    if ext in (".csv", ".tsv"):
        text = read_text(path)
        first_line = text.split("\n", 1)[0]
        delimiter = "\t" if ext == ".tsv" else max(",;\t", key=first_line.count)
        return list(csv.reader(io.StringIO(text), delimiter=delimiter)), None
    if ext == ".txt":
        lines = (line.split("#", 1)[0].strip() for line in read_text(path).splitlines())
        return [["name"]] + [[line] for line in lines if line], None
    if ext == ".xls":
        raise SystemExit(f"{path}: old .xls format; save it as .xlsx or .csv first")
    raise SystemExit(f"{path}: unsupported file type; use .xlsx, .csv or .txt")


def cell(row, i):
    return clean(row[i]) if i is not None and i < len(row) else ""


def profile(rows, col):
    """What a column holds, as counts, so it can be judged without showing any values."""
    values = [v for v in (cell(r, col) for r in rows[1:]) if v]
    return {
        "values": len(values),
        "distinct": len(set(values)),
        "arabic": sum(1 for v in values if _ARABIC.search(v)),
        "latin": sum(1 for v in values if _LATIN.search(v) and "@" not in v),
        "numbers": sum(1 for v in values if re.fullmatch(r"[\d٠-٩۰-۹ .\-]+", v)),
        "emails": sum(1 for v in values if "@" in v),
        "words": sum(len(v.split()) for v in values) / len(values) if values else 0,
    }


def detect(header, rows):
    """Which columns hold typed names, the account name, emails and the student ID."""
    keys = [normalize(h) for h in header]
    ms_forms = "start time" in keys and "completion time" in keys
    names, emails, ids, account = [], [], [], None
    for i, k in enumerate(keys):
        # Microsoft Forms quizzes repeat each question as "Points - ..." and "Feedback - ...".
        if not k or k.startswith(("points ", "feedback ")):
            continue
        if k == "name" and ms_forms:
            # The Microsoft account's display name, not something the student typed.
            account = i
        elif k.startswith(_ID_STARTS) or any(w in k for w in _ID_WORDS):
            ids.append(i)
        elif k.startswith(_NAME_STARTS) or k == "name" or any(w in k for w in _NAME_WORDS):
            names.append(i)
        elif k.startswith("البريد") or "mail" in k:
            emails.append(i)
    # The column with the most Arabic names is shown; any others are extra spellings.
    names.sort(key=lambda i: -profile(rows, i)["arabic"])
    return {"names": names, "account": account, "emails": emails, "id": ids[0] if ids else None}


def column(header, spec):
    """The index of a column given by its header (or the header's start) or 1-based number."""
    if spec.isdigit() and 1 <= int(spec) <= len(header):
        return int(spec) - 1
    wanted = normalize(spec)
    keys = [normalize(h) for h in header]
    if wanted in keys:
        return keys.index(wanted)
    starts = [i for i, k in enumerate(keys) if wanted and k.startswith(wanted)]
    return starts[0] if len(starts) == 1 else None


def headers_hint(header):
    shown = "; ".join(f"{i + 1}. {h[:40]}" for i, h in enumerate(header[:40]))
    return shown + (f" … and {len(header) - 40} more" if len(header) > 40 else "")


def one_column(header, spec, path, flag):
    """A column chosen on the command line: its index, or None for 'none'."""
    if spec.lower() == "none":
        return None
    i = column(header, spec)
    if i is None:
        raise SystemExit(f"{path}: no column {spec!r} for {flag}; columns: {headers_hint(header)}")
    return i


def override(cols, header, args, path):
    """Apply the column options given on the command line to one file's detected columns."""
    if args.name_column:
        found = [i for i in (column(header, s) for s in args.name_column) if i is not None]
        if not found:
            raise SystemExit(
                f"{path}: none of --name-column {args.name_column} is here; columns: {headers_hint(header)}"
            )
        cols["names"] = found
    if args.account_column:
        cols["account"] = one_column(header, args.account_column, path, "--account-column")
    if args.email_column:
        specs = [s for s in args.email_column if s.lower() != "none"]
        cols["emails"] = [one_column(header, s, path, "--email-column") for s in specs]
    if args.id_column:
        cols["id"] = one_column(header, args.id_column, path, "--id-column")


def student_id(value):
    """An ID as text: Arabic-Indic digits converted, spaces dropped, Excel's trailing ".0" removed."""
    v = clean(value).translate(_DIGITS).replace(" ", "")
    if re.fullmatch(r"\d+\.0", v):
        v = v[:-2]
    return v.lower()


def emails_in(text):
    """A cell sometimes holds more than one address; "anonymous" holds none."""
    return [e.lower() for e in re.split(r"[\s,;/]+", clean(text)) if "@" in e]


def load_people(paths, args):
    """Every submission in the files, linked into people across rows and files."""
    records, used = [], []
    for f_i, path in enumerate(paths):
        rows, sheet = read_table(path, args.people_sheet)
        header = [clean(h) for h in rows[0]] if rows else []
        cols = detect(header, rows)
        override(cols, header, args, path)
        if rows and not cols["names"]:
            raise SystemExit(f"{path}: no name column found; pass --name-column (`inspect` lists the columns)")
        for r in rows[1:]:
            names = [n for n in (cell(r, i) for i in cols["names"]) if n]
            raw_emails = " ".join(cell(r, i) for i in cols["emails"])
            emails = unique(emails_in(raw_emails))
            sid = student_id(cell(r, cols["id"]))
            if not sid and args.id_pattern:
                m = re.search(args.id_pattern, raw_emails)
                if m:
                    sid = student_id(m.group(1) if m.groups() else m.group(0))
            if names or emails or sid:
                records.append(
                    {"file": f_i, "names": names, "account": cell(r, cols["account"]), "emails": emails, "id": sid}
                )
        used.append({"path": path, "sheet": sheet, "rows": max(len(rows) - 1, 0), "header": header, "cols": cols})
    return link(records), used


def link(records):
    """Group submissions that share an email, a student ID or an exactly matching name."""
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, rec in enumerate(records):
        keys = [("email", e) for e in rec["emails"]]
        keys += [("id", rec["id"])] if rec["id"] else []
        # Not account names: students sometimes fill in a form on someone else's account.
        keys += [("name", arabic_names.key(n)) for n in rec["names"]]
        for k in keys:
            if not k[1]:
                continue
            if k in seen:
                parent[find(i)] = find(seen[k])
            else:
                seen[k] = i

    groups = {}
    for i, rec in enumerate(records):
        groups.setdefault(find(i), []).append(rec)

    people = []
    for recs in groups.values():
        typed = unique(n for r in recs for n in r["names"])
        accounts = unique(r["account"] for r in recs if r["account"])
        # Prefer an Arabic spelling, then the most complete one.
        shown = max(typed, key=lambda n: (bool(_ARABIC.search(n)), len(normalize(n).split()), len(n)), default="")
        people.append(
            {
                "name": shown or (accounts[0] if accounts else ""),
                "spellings": typed + [a for a in accounts if a not in typed],
                "ids": unique(r["id"] for r in recs if r["id"]),
                "emails": unique(e for r in recs for e in r["emails"]),
                "files": sorted({r["file"] for r in recs}),
            }
        )
    people.sort(key=lambda p: normalize(p["name"]))
    for i, p in enumerate(people):
        p["key"] = i
    return people


def load_list(path, args):
    """The names to look for, each with its student ID if the list has one."""
    rows, sheet = read_table(path, args.names_sheet)
    if len(rows) < 2:
        raise SystemExit(f"{path}: no names found")
    header = [clean(h) for h in rows[0]]
    cols = detect(header, rows)
    if args.names_column:
        name_col = one_column(header, args.names_column, path, "--names-column")
    else:
        name_col = cols["names"][0] if cols["names"] else None
    if name_col is None:
        raise SystemExit(f"{path}: no name column found; pass --names-column (`inspect` lists the columns)")
    id_col = cols["id"]
    if args.names_id_column:
        id_col = one_column(header, args.names_id_column, path, "--names-id-column")
    entries = [
        {"name": cell(r, name_col), "id": student_id(cell(r, id_col))} for r in rows[1:] if cell(r, name_col)
    ]
    cols = {"names": [name_col], "account": None, "emails": [], "id": id_col}
    return entries, {"path": path, "sheet": sheet, "rows": len(rows) - 1, "header": header, "cols": cols}


def find_people(ref, people):
    """The people a confirmations line points at: by student ID, email, or one of their spellings."""
    sid, email, name_key = student_id(ref), ref.strip().lower(), arabic_names.key(ref)
    hits = [p for p in people if sid in p["ids"]]
    hits = hits or [p for p in people if email in p["emails"]]
    hits = hits or [p for p in people if name_key and name_key in {arabic_names.key(s) for s in p["spellings"]}]
    return hits


def read_confirmations(path, entries, people):
    """(confirmed {name: person key}, rejected {(name, person key)}) from a decisions file."""
    on_list = {}
    for e in entries:
        on_list.setdefault(normalize(e["name"]), e["name"])
    confirmed, rejected, problems = {}, set(), []
    for n, line in enumerate(read_text(path).splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"(.+?)\s*(!=|=)\s*(.+)", line)
        if not m:
            problems.append(f"line {n}: expected 'name = person' or 'name != person'")
            continue
        left, op, right = m.groups()
        name = on_list.get(normalize(left))
        hits = find_people(right, people)
        if name is None:
            problems.append(f"line {n}: {left!r} is not on the list")
        elif not hits:
            problems.append(f"line {n}: {right!r} matches no one in the files")
        elif len(hits) > 1:
            problems.append(f"line {n}: {right!r} matches {len(hits)} people; use their student ID or email")
        elif op == "!=":
            rejected.add((name, hits[0]["key"]))
        elif confirmed.get(name, hits[0]["key"]) != hits[0]["key"]:
            problems.append(f"line {n}: {left!r} is already confirmed as someone else")
        else:
            confirmed[name] = hits[0]["key"]
    if problems:
        raise SystemExit(f"{path}:\n  " + "\n  ".join(problems))
    return confirmed, rejected


# ---------------------------------------------------------------- matching

def match_list(entries, people, confirmed, rejected):
    """One outcome per entry on the list: matched by student ID first, then by name."""
    roster_ids = [e["id"] for e in entries if e["id"]]
    by_id = {}
    for p in people:
        for sid in p["ids"]:
            by_id.setdefault(sid, []).append(p["key"])
    id_matches = {}
    for i, e in enumerate(entries):
        # Only an ID that is unique on both sides settles a match.
        if e["id"] and roster_ids.count(e["id"]) == 1 and len(by_id.get(e["id"], [])) == 1:
            id_matches[i] = by_id[e["id"]][0]

    taken = set(id_matches.values())
    rest = [e["name"] for i, e in enumerate(entries) if i not in id_matches]
    kept = {}
    for name, key in confirmed.items():
        if key in taken:
            raise SystemExit(f"confirmation for {name!r}: that person is already matched by student ID")
        if name in rest:  # otherwise its row was matched by ID already
            kept[name] = key
    candidates = {p["key"]: p["spellings"] for p in people if p["key"] not in taken}
    result = arabic_names.match(rest, candidates, kept, rejected)

    outcomes = []
    for i, e in enumerate(entries):
        name = e["name"]
        if i in id_matches:
            key = id_matches[i]
            fits = arabic_names.match([name], {key: people[key]["spellings"]})
            outcome = {"status": "matched", "hit": arabic_names.Hit(key, "id", "")}
            outcome["differs"] = not (fits.matched or fits.review)
        elif name in result.matched:
            outcome = {"status": "matched", "hit": result.matched[name]}
        elif name in result.ambiguous:
            outcome = {"status": "ambiguous", "hits": result.ambiguous[name], "twice": rest.count(name) > 1}
        elif name in result.review:
            outcome = {"status": "check", "hits": result.review[name]}
        else:
            outcome = {"status": "missing"}
        outcomes.append(outcome)
    return outcomes


def grouped(hits):
    """Hits per person, in order: [(person key, [(rule, spelling it rests on)])]."""
    out = {}
    for h in hits:
        out.setdefault(h.person, []).append((h.rule, h.spelling))
    return list(out.items())


# ---------------------------------------------------------------- output

LABELS = {
    "en": {
        "sheets": ("Results", "To check", "People in the files", "Columns used"),
        "results": ("#", "Name on the list", "Status", "Matched to", "ID", "How", "Matched spelling"),
        "count": "Files",
        "note": "Note",
        "check": ("Name on the list", "Possible match", "ID", "Why", "Spelling", "Note"),
        "people": ("Name", "ID", "Emails", "Other spellings", "Matched to"),
        "used": ("File", "Sheet", "Rows", "Name columns", "Account name", "Emails", "Student ID"),
        "status": {"matched": "matched", "check": "check", "ambiguous": "ambiguous", "missing": "not found"},
        "rules": {
            "id": "student ID",
            "confirmed": "confirmed",
            "exact": "exact",
            "spacing": "word breaks differ",
            "shorter": "shorter name",
            "latin": "Latin spelling",
            "partial": "only two names agree",
            "latin-partial": "Latin spelling, two names agree",
            "typo": "one letter differs",
        },
        "notes": {
            "taken": "already matched to {}",
            "differs": "the ID matches but the name doesn't",
            "twice": "listed more than once",
            "several": "fits several people equally",
            "ids": "records under more than one ID: {}",
        },
    },
    "ar": {
        "sheets": ("النتائج", "للمراجعة", "الأشخاص في الملفات", "الأعمدة المستخدمة"),
        "results": ("م", "الاسم في القائمة", "الحالة", "المطابق", "الرقم", "طريقة المطابقة", "الاسم كما كُتب"),
        "count": "عدد الملفات",
        "note": "ملاحظة",
        "check": ("الاسم في القائمة", "مطابقة محتملة", "الرقم", "السبب", "الاسم كما كُتب", "ملاحظة"),
        "people": ("الاسم", "الرقم", "البريد", "كتابات أخرى للاسم", "المطابق في القائمة"),
        "used": ("الملف", "الورقة", "الصفوف", "أعمدة الاسم", "اسم الحساب", "البريد", "الرقم"),
        "status": {"matched": "مطابق", "check": "يحتاج تأكيد", "ambiguous": "أكثر من احتمال", "missing": "غير موجود"},
        "rules": {
            "id": "الرقم",
            "confirmed": "مؤكد",
            "exact": "تطابق تام",
            "spacing": "اختلاف المسافات",
            "shorter": "اسم مختصر",
            "latin": "بالحروف اللاتينية",
            "partial": "يتفق اسمان فقط",
            "latin-partial": "بالحروف اللاتينية، يتفق اسمان فقط",
            "typo": "اختلاف حرف واحد",
        },
        "notes": {
            "taken": "مطابق مسبقًا لـ {}",
            "differs": "الرقم مطابق لكن الاسم مختلف",
            "twice": "مكرر في القائمة",
            "several": "يطابق أكثر من شخص بالدرجة نفسها",
            "ids": "سجلات بأكثر من رقم: {}",
        },
    },
}
PRESENT = "✓"


def file_label(path, taken):
    """A short column title for a file: its name without extension or Forms' "(1-44)" counter."""
    stem = os.path.splitext(os.path.basename(path))[0]
    label = clean(re.sub(r"\s*\(\d+-\d+\)(\(\d+\))?\s*$", "", stem)).strip(" .") or stem
    base, n = label, 2
    while label in taken:
        label, n = f"{base} ({n})", n + 1
    taken.add(label)
    return label


def owners(entries, outcomes):
    """Person key -> the name on the list it was matched to."""
    return {o["hit"].person: e["name"] for e, o in zip(entries, outcomes) if o["status"] == "matched"}


def presence(person, n_files):
    return [PRESENT if f in person["files"] else "" for f in range(n_files)]


def result_rows(entries, outcomes, people, n_files, L):
    rows = []
    for n, (e, o) in enumerate(zip(entries, outcomes), 1):
        row = [n, e["name"], L["status"][o["status"]]]
        if o["status"] == "matched":
            p = people[o["hit"].person]
            spelling = o["hit"].spelling if o["hit"].spelling != p["name"] else ""
            row += [p["name"], " / ".join(p["ids"]), L["rules"][o["hit"].rule], spelling]
            row += presence(p, n_files) + [len(p["files"]), L["notes"]["differs"] if o.get("differs") else ""]
        else:
            note = ""
            if o["status"] == "ambiguous":
                note = L["notes"]["twice"] if o["twice"] else L["notes"]["several"]
            row += ["", "", "", ""] + [""] * n_files + [0, note]
        rows.append(row)
    return rows


def check_rows(entries, outcomes, people, owner, L):
    rows = []
    for e, o in zip(entries, outcomes):
        if o.get("differs"):
            p = people[o["hit"].person]
            rows.append([e["name"], p["name"], " / ".join(p["ids"]), L["rules"]["id"], "", L["notes"]["differs"]])
        for key, evidence in grouped(o.get("hits", [])):
            p = people[key]
            if o["status"] == "ambiguous":
                note = L["notes"]["twice"] if o["twice"] else L["notes"]["several"]
            else:
                note = L["notes"]["taken"].format(owner[key]) if key in owner else ""
            # One reason per spelling, in the same order in both columns.
            why = " / ".join(L["rules"][rule] for rule, _ in evidence)
            spellings = " / ".join(spelling for _, spelling in evidence)
            rows.append([e["name"], p["name"], " / ".join(p["ids"]), why, spellings, note])
    for p in people:
        if len(p["ids"]) > 1:
            note = L["notes"]["ids"].format(" / ".join(p["ids"]))
            rows.append([owner.get(p["key"], ""), p["name"], "", "", "", note])
    return rows


def people_rows(people, owner, n_files):
    rows = []
    # People who match no name on the list come first: they are the ones to look at.
    for p in sorted(people, key=lambda p: p["key"] in owner):
        others = " / ".join(s for s in p["spellings"] if s != p["name"])
        rows.append(
            [p["name"], " / ".join(p["ids"]), " / ".join(p["emails"]), others, owner.get(p["key"], "")]
            + presence(p, n_files)
            + [len(p["files"])]
        )
    return rows


def used_rows(used):
    rows = []
    for u in used:
        header, cols = u["header"], u["cols"]

        def title(i):
            return header[i] if i is not None and i < len(header) else ""

        names = " / ".join(title(i) for i in cols["names"])
        emails = " / ".join(title(i) for i in cols["emails"])
        rows.append(
            [os.path.basename(u["path"]), u["sheet"] or "", u["rows"], names, title(cols["account"]), emails,
             title(cols["id"])]
        )
    return rows


def write_results(path, lang, entries, outcomes, people, labels, used):
    """The workbook: results per name on the list, things to check, everyone found, columns read."""
    L = LABELS[lang]
    owner = owners(entries, outcomes)
    n_files = len(labels)
    sheets = []

    def add(name, header, rows, widths, freeze=(1, 1), highlights=()):
        sheets.append(
            {
                "name": name,
                "rows": [list(header)] + rows,
                "rtl": lang == "ar",
                "widths": widths,
                "styles": {(0, c): xlsx_lite.HEADER for c in range(len(header))},
                "autofilter": xlsx_lite.span(0, 0, max(len(rows), 1), len(header) - 1),
                "freeze": freeze,
                "highlights": [h for h in highlights if h],
            }
        )

    def ticks(rows, first_col):
        if rows and n_files:
            return (xlsx_lite.span(1, first_col, len(rows), first_col + n_files - 1), {PRESENT: xlsx_lite.GOOD})
        return None

    if entries:
        rows = result_rows(entries, outcomes, people, n_files, L)
        status = {L["status"]["matched"]: xlsx_lite.GOOD}
        status.update({L["status"][s]: xlsx_lite.BAD for s in ("check", "ambiguous", "missing")})
        add(
            L["sheets"][0],
            list(L["results"]) + labels + [L["count"], L["note"]],
            rows,
            [5, 30, 14, 30, 12, 18, 26] + [12] * n_files + [10, 30],
            freeze=(1, 2),
            highlights=[(xlsx_lite.span(1, 2, len(rows), 2), status), ticks(rows, 7)],
        )
    add(L["sheets"][1], L["check"], check_rows(entries, outcomes, people, owner, L), [30, 30, 14, 30, 34, 34])
    rows = people_rows(people, owner, n_files)
    add(
        L["sheets"][2],
        list(L["people"]) + labels + [L["count"]],
        rows,
        [30, 14, 30, 40, 30] + [12] * n_files + [10],
        highlights=[ticks(rows, 5)],
    )
    add(L["sheets"][3], L["used"], used_rows(used), [40, 20, 8, 40, 16, 30, 20], freeze=(1, 0))
    xlsx_lite.write_workbook(path, sheets)


def describe(people, key, evidence, n_files):
    """A person, the evidence for them and their attendance: 'name (id)  [rule via "spelling"]  in 2 of 3 files'."""
    p = people[key]
    ids = f" ({' / '.join(p['ids'])})" if p["ids"] else ""
    reasons = "; ".join(f'{rule} via "{spelling}"' if spelling else rule for rule, spelling in evidence)
    return f"{p['name']}{ids}  [{reasons}]  in {len(p['files'])} of {n_files} files"


def print_lines(title, lines, limit=60):
    print(f"{title}: {len(lines)}")
    for line in lines[:limit]:
        print(f"  {line}")
    if len(lines) > limit:
        print(f"  … and {len(lines) - limit} more (see the workbook)")


def print_summary(entries, outcomes, people, list_used, n_files):
    owner = owners(entries, outcomes)
    if entries:
        column_name = list_used["header"][list_used["cols"]["names"][0]]
        print(f"list: {len(entries)} names ({os.path.basename(list_used['path'])}, column {column_name!r})")
        matched = [(e, o) for e, o in zip(entries, outcomes) if o["status"] == "matched"]
        by_rule = {}
        for _, o in matched:
            by_rule[o["hit"].rule] = by_rule.get(o["hit"].rule, 0) + 1
        print(f"rules: {', '.join(f'{r} {n}' for r, n in sorted(by_rule.items()))}")
        # Matches worth a second look first, so a long list never cuts them off.
        matched.sort(key=lambda eo: eo[1]["hit"].rule in ("exact", "id") and not eo[1].get("differs"))
        lines = []
        for e, o in matched:
            hit = o["hit"]
            # The spelling is worth showing only when it isn't the name shown anyway.
            spelling = hit.spelling if hit.spelling != people[hit.person]["name"] else ""
            flag = "  <- the ID matches but the name doesn't; check" if o.get("differs") else ""
            lines.append(f"{e['name']}  ->  {describe(people, hit.person, [(hit.rule, spelling)], n_files)}{flag}")
        print_lines("matched", lines)

        lines = []
        for e, o in zip(entries, outcomes):
            if o["status"] == "check":
                for key, evidence in grouped(o["hits"]):
                    taken = f"  (already matched to {owner[key]})" if key in owner else ""
                    lines.append(f"{e['name']}  ?  {describe(people, key, evidence, n_files)}{taken}")
        print_lines("to check (possible matches, not applied)", lines)

        lines = []
        for e, o in zip(entries, outcomes):
            if o["status"] == "ambiguous":
                why = "listed more than once" if o["twice"] else "fits several people equally"
                options = " | ".join(describe(people, key, ev, n_files) for key, ev in grouped(o["hits"]))
                lines.append(f"{e['name']}  ({why}){': ' + options if options else ''}")
        print_lines("ambiguous (not applied)", lines)

        print_lines("not found", [e["name"] for e, o in zip(entries, outcomes) if o["status"] == "missing"])
        unlisted = [p for p in people if p["key"] not in owner]
        print_lines(
            "people in the files but not on the list",
            [f"{p['name']}  in {len(p['files'])} of {n_files} files" for p in unlisted],
        )
    several = [p for p in people if len(p["ids"]) > 1]
    if several:
        print(f"records under more than one student ID (a typo, or two people sharing a name): {len(several)}")
        for p in several:
            print(f"  {p['name']}: {' / '.join(p['ids'])}")


# ---------------------------------------------------------------- commands

def run_match(args):
    if args.names:
        for path in args.people:
            if os.path.exists(path) and os.path.exists(args.names) and os.path.samefile(path, args.names):
                raise SystemExit(f"{path} is both the list (--names) and one of the files (--people)")
    people, used = load_people(args.people, args)
    entries, list_used = load_list(args.names, args) if args.names else ([], None)
    confirmed, rejected = {}, set()
    if args.confirmations:
        confirmed, rejected = read_confirmations(args.confirmations, entries, people)
    outcomes = match_list(entries, people, confirmed, rejected) if entries else []

    taken = set()
    labels = [file_label(p, taken) for p in args.people]
    all_used = ([list_used] if list_used else []) + used
    write_results(args.out, args.lang, entries, outcomes, people, labels, all_used)

    print(f"files: {len(args.people)} ({sum(u['rows'] for u in used)} rows) -> {len(people)} people")
    print_summary(entries, outcomes, people, list_used, len(args.people))
    print(f"workbook: {args.out}")


def run_inspect(args):
    for path in args.files:
        rows, sheet = read_table(path, args.sheet)
        print(path)
        if path.lower().endswith((".xlsx", ".xlsm")):
            sheets = xlsx_lite.sheet_names(path)
            sizes = [f"{s} ({max(len(xlsx_lite.read_sheet(path, i)) - 1, 0)} rows)" for i, s in enumerate(sheets)]
            print(f"  sheets: {', '.join(sizes)}; reading: {sheet}")
        print(f"  rows: {max(len(rows) - 1, 0)}")
        if not rows:
            continue
        header = [clean(h) for h in rows[0]]
        cols = detect(header, rows)
        marks = {i: "name" if n == 0 else "other name" for n, i in enumerate(cols["names"])}
        marks.update({i: "email" for i in cols["emails"]})
        if cols["account"] is not None:
            marks[cols["account"]] = "account name"
        if cols["id"] is not None:
            marks[cols["id"]] = "student ID"
        hidden = 0
        for i, h in enumerate(header):
            p = profile(rows, i)
            # Columns of repeated answers (ratings, choices) or long free text can't hold names.
            plausible = p["values"] and p["distinct"] / p["values"] >= 0.6 and p["words"] <= 6
            if not (args.all or i in marks or plausible):
                hidden += 1
                continue
            kinds = [f"{p[k]} {k}" for k in ("arabic", "latin", "numbers", "emails") if p[k]]
            mark = f"   <- {marks[i]}" if i in marks else ""
            print(f"  {i + 1:>3}. {h[:60]}  [{p['values']} values{': ' + ', '.join(kinds) if kinds else ''}]{mark}")
        if hidden:
            print(f"  ({hidden} more columns of repeated answers or long text; --all lists them)")
        if not cols["names"]:
            print("  no name column found; pass --name-column / --names-column")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="show the sheets and the columns that would be read", allow_abbrev=False)
    p.add_argument("files", nargs="+")
    p.add_argument("--sheet", help="sheet name or 1-based number (default: the first)")
    p.add_argument("--all", action="store_true", help="list every column")

    p = sub.add_parser("match", help="match a list of names against the people in the files", allow_abbrev=False)
    p.add_argument("--names", help="the list to look for: .xlsx, .csv, or .txt with one name per line")
    p.add_argument("--names-sheet", help="sheet of the list (name or 1-based number)")
    p.add_argument("--names-column", help="the list's name column (header text or 1-based number)")
    p.add_argument("--names-id-column", help="the list's student ID column, or 'none'")
    p.add_argument("--people", nargs="+", required=True, help="files where people appear, e.g. one export per session")
    p.add_argument("--people-sheet", help="sheet to read in each file (default: the first)")
    p.add_argument("--name-column", action="append", help="typed-name column in the files; repeat for more")
    p.add_argument("--account-column", help="account display-name column in the files, or 'none'")
    p.add_argument("--email-column", action="append", help="email column in the files; repeat for more, or 'none'")
    p.add_argument("--id-column", help="student ID column in the files, or 'none'")
    p.add_argument("--id-pattern", help=r"regex that takes the student ID out of an email, e.g. '(\d{7})@'")
    p.add_argument("--confirmations", help="decisions file: 'name = person' or 'name != person' per line")
    p.add_argument("--out", default="matching-results.xlsx", help="workbook to write")
    p.add_argument("--lang", choices=("ar", "en"), default="ar", help="language of the workbook (default: ar)")

    args = parser.parse_args(argv)
    if args.command == "inspect":
        run_inspect(args)
    else:
        run_match(args)


if __name__ == "__main__":
    main()
