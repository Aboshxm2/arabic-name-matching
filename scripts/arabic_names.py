"""Normalise and match Arabic personal names, including Latin-script spellings.

Made for attendance: finding the students on a roster among whatever they typed
into sign-in forms. It knows nothing about forms or workbooks and needs only the
standard library, so this file can be copied into another project as is.

    result = arabic_names.match(
        ["نورة الحربي", "هيا محمد الشهري"],           # the names to find
        {"4500001": ["نورة سعد الحربي"],              # any key -> every spelling
         "4500002": ["هيا محمد", "HAYA ALSHAHRI"]},   # seen for that person
    )
    result.matched["نورة الحربي"]
    # Hit(person='4500001', rule='shorter', spelling='نورة سعد الحربي')
    result.review["هيا محمد الشهري"]
    # [Hit(person='4500002', rule='partial', spelling='هيا محمد'),
    #  Hit(person='4500002', rule='latin-partial', spelling='HAYA ALSHAHRI')]

The rules, strongest first. Only the first five are applied; the rest are
offered for review, because a wrong match silently credits the wrong person
while a missed one at least shows up as unmatched.

    confirmed      passed in by the caller, e.g. after a person checked a suggestion
    exact          the same once letter forms, diacritics and بن/بنت are evened out
    spacing        the same letters with different word breaks: "محمدعلي" / "محمد علي"
    shorter        one spelling leaves parts out but keeps the order, and either the
                   given and family names agree or three parts line up
    latin          a Latin spelling with three parts lining up, whose given name
                   agrees with the person's Arabic spelling
    partial        only two parts line up, e.g. the given and father's names
    latin-partial  only two parts of a Latin spelling line up (account names are
                   often just given and family name), or its given name disagrees
                   with the person's Arabic spelling
    typo           exact or shorter but for one letter, outside the given name
"""

import functools
import re
import unicodedata
from collections import Counter, namedtuple

Hit = namedtuple("Hit", "person rule spelling")
Result = namedtuple("Result", "matched ambiguous unmatched review")

APPLIED = ("confirmed", "exact", "spacing", "shorter", "latin")
FOR_REVIEW = ("partial", "latin-partial", "typo")
RULES = APPLIED + FOR_REVIEW

# Characters that come along when text is copied out of forms, PDFs and chat
# apps: no-break and zero-width spaces, bidi marks.
_INVISIBLE = dict.fromkeys(
    [
        0x00A0, 0x061C, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B,
        0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF,
    ],
    " ",
)


def clean(text):
    """Strip NBSP / bidi marks and collapse whitespace."""
    if text is None:
        return ""
    return " ".join(str(text).translate(_INVISIBLE).split())


_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_LETTERS = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي",
        # Persian keyboards type these for ك ي ه.
        "ک": "ك", "ی": "ي", "ھ": "ه", "ہ": "ه", "ە": "ه", "ۀ": "ه",
    }
)
_APOSTROPHES = re.compile(r"['`´‘’ʻʼʾʿ]")
_PUNCTUATION = re.compile(r"[^\w\s]|_")
_CONNECTORS = {"بن", "بنت", "ابن", "bin", "bint", "ibn"}
_ARABIC = re.compile(r"[ء-ي]")
_LATIN = re.compile(r"[a-z]")


def normalize(name):
    """Even out letter forms, diacritics, punctuation and بن/بنت for comparison.

    Word breaks are kept, since they separate the parts of the name; match()
    allows for them separately.
    """
    s = unicodedata.normalize("NFKC", clean(name))
    s = _DIACRITICS.sub("", s).translate(_LETTERS)
    s = _PUNCTUATION.sub(" ", _APOSTROPHES.sub("", s)).lower()
    parts = []
    for part in s.split():
        # A lone letter is an initial or a title ("د."), not part of the name.
        if part in _CONNECTORS or len(part) < 2:
            continue
        # PDF text extraction reorders lam-alef: "االء" for "الاء", "عبدهللا" for "عبدالله".
        part = part.replace("هللا", "الله")
        if part.startswith("اال"):
            part = "الا" + part[3:]
        parts.append(part)
    return " ".join(parts)


def key(name):
    """normalize() without spaces, so spellings that differ only in word breaks share it."""
    return normalize(name).replace(" ", "")


# Consonant classes shared by Arabic letters and the Latin letters used for
# them, for comparing a name across scripts. Long vowels, ع and ء are dropped
# like Latin vowels, so "سديم" and "Sadeem" come out the same. Letters that are
# romanised interchangeably share a class (ق غ ك خ, and ت ط د ض ث), and a Latin
# letter can stand for several: "g" for ق or ج ("Algahtani", "Alguhani"),
# "z", "th" and "dh" for ذ or ظ ("Alzahabi", "Dhafer").
_SOUNDS = {
    "ب": "b", "ت": "t", "ث": "t", "ج": "j", "ح": "h", "خ": "k", "د": "t",
    "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "x", "ص": "s", "ض": "t",
    "ط": "t", "ظ": "z", "غ": "k", "ف": "f", "ق": "k", "ك": "k", "ل": "l",
    "م": "m", "ن": "n", "ه": "h",
    "b": "b", "p": "b", "t": "t", "d": "t", "j": "j", "h": "h", "k": "k",
    "q": "k", "g": "kj", "c": "k", "r": "r", "z": "z", "s": "s", "x": "x",
    "f": "f", "v": "f", "l": "l", "m": "m", "n": "n", "θ": "tz", "ð": "tz",
}
_DIGRAPHS = (
    ("kh", "k"), ("gh", "k"), ("sh", "x"), ("ch", "x"), ("th", "θ"), ("dh", "ð"), ("ph", "f"),
)


def _classes(part, first):
    """The consonant classes each sounded letter of a name part can stand for."""
    arabic = bool(_ARABIC.search(part))
    if not first:
        # Family names come with or without the article: "الحربي", "Alharbi", "Harbi".
        # The given name keeps it, or "Ilham" would not match "الهام".
        if arabic and part.startswith("ال") and len(part) > 3:
            part = part[2:]
        elif not arabic and part.startswith(("al", "el")) and len(part) > 4:
            part = part[2:]
    if not arabic:
        for pair, letter in _DIGRAPHS:
            part = part.replace(pair, letter)
    return [_SOUNDS[ch] for ch in part if ch in _SOUNDS]


@functools.lru_cache(maxsize=None)
def _sounds(part, first):
    """Consonant skeletons of a name part, comparable across scripts: one per reading."""
    skeletons = {""}
    for options in _classes(part, first):
        # Doubled letters collapse: "Mohammed" and "محمد" come out the same.
        skeletons = {s if s.endswith(c) else s + c for s in skeletons for c in options}
    # A final ة or ه is often left off in Latin: "Fatima" for "فاطمة".
    return frozenset(s[:-1] if len(s) > 1 and s.endswith("h") else s for s in skeletons) - {""}


def _same_letters(a, b, first):
    return a == b


def _same_sound(a, b, first):
    return bool(_sounds(a, first) & _sounds(b, first))


def _one_typo(a, b):
    """True when a and b differ by one added, dropped, changed or swapped letter."""
    if a == b or min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) < len(b):
        return a[i:] == b[i + 1:]
    swapped = a[i + 1:i + 2] + a[i:i + 1] + a[i + 2:]
    return a[i + 1:] == b[i + 1:] or swapped == b[i:]


def _fits(short, long, same, typos=0):
    """Ways to fit every part of `short` into `long`, in order, from the given name on.

    Parts may be joined on either side ("عبد العزيز" against "عبدالعزيز"), parts
    of `long` may be left out (middle names), and up to `typos` parts after the
    given name may be a letter off. Returns a set of (parts matched, last parts
    line up) pairs, empty when `short` doesn't fit.
    """

    @functools.lru_cache(maxsize=None)
    def go(i, j, typos_left):
        if i == len(short):
            return {(0, j == len(long))}
        out = set()
        for a in range(1, min(3, len(short) - i) + 1):
            for b in range(1, min(3, len(long) - j) + 1):
                s, t = "".join(short[i:i + a]), "".join(long[j:j + b])
                if same(s, t, i == 0):
                    rest = go(i + a, j + b, typos_left)
                elif typos_left and i and _one_typo(s, t):
                    rest = go(i + a, j + b, typos_left - 1)
                else:
                    continue
                out |= {(n + 1, last) for n, last in rest}
        if i and j < len(long):
            out |= go(i, j + 1, typos_left)
        return out

    return go(0, 0, typos)


def _strength(a, b, same, latin, typos=0):
    """2 when one name fits the other well enough to apply, 1 for review only, else 0."""
    best = 0
    for short, long in ((a, b), (b, a)):
        for parts, last in _fits(short, long, same, typos):
            if parts >= 3 or (parts == 2 and last and not latin):
                return 2
            if parts == 2:
                best = 1
    return best


_Spelling = namedtuple("_Spelling", "text parts joined arabic lead")


def _prepare(text):
    parts = tuple(normalize(text).split())
    joined = "".join(parts)
    arabic = bool(_ARABIC.search(joined)) and not _LATIN.search(joined)
    classes = _classes(joined, True)
    return _Spelling(text, parts, joined, arabic, frozenset(classes[0] if classes else ""))


def _compare(a, b):
    """The strongest rule under which two prepared spellings fit, or None."""
    if a.parts == b.parts:
        return "exact"
    if a.joined == b.joined:
        return "spacing"
    if a.arabic and b.arabic:
        # The given names have to agree, so a different first letter settles it.
        if a.joined[0] != b.joined[0]:
            return None
        strength = _strength(a.parts, b.parts, _same_letters, latin=False)
        if strength == 2:
            return "shorter"
        if strength == 1:
            return "partial"
        if _strength(a.parts, b.parts, _same_letters, latin=False, typos=1) == 2:
            return "typo"
        return None
    if not a.lead & b.lead:
        return None
    strength = _strength(a.parts, b.parts, _same_sound, latin=True)
    if strength == 2:
        return "latin"
    if strength == 1:
        return "latin-partial"
    return None


def _same_start(a, b):
    """True when two lists of name parts begin with the same given name, however spaced."""
    return any("".join(a[:i]) == "".join(b[:j]) for i in (1, 2, 3) for j in (1, 2, 3))


def _hits(query, person, spellings):
    """One Hit per rule under which some spelling of the person fits the query, best first."""
    # Latin can't tell some given names apart ("Ali" and "Ola" are علي and علا),
    # and siblings share the rest of the name, so a Latin spelling isn't applied
    # when the person's Arabic spellings disagree on the given name.
    arabic = [s for s in spellings if s.arabic]
    given_agrees = not query.arabic or not arabic or any(
        _same_start(query.parts, s.parts) for s in arabic
    )
    hits = {}
    for s in spellings:
        rule = _compare(query, s)
        if rule == "latin" and not given_agrees:
            rule = "latin-partial"
        if rule and rule not in hits:
            hits[rule] = Hit(person, rule, s.text)
    return sorted(hits.values(), key=lambda h: RULES.index(h.rule))


def _tier(rule):
    """Applied rules that are equally certain; a name fitting two people in one tier is ambiguous."""
    if rule == "confirmed":
        return -1
    return 0 if rule in ("exact", "spacing") else 1


def match(names, people, confirmed=None, rejected=()):
    """Find each of `names` among `people`, a mapping of key -> list of spellings.

    Returns Result(matched, ambiguous, unmatched, review):
      matched    {name: Hit}, applied
      ambiguous  {name: [Hit]}, nothing applied: several people fit equally well,
                 another name fits the same person equally well, or the name is
                 listed more than once
      unmatched  [name], no applied match
      review     {name: [Hit]}, possible matches for unmatched names, best first,
                 for a person to check

    A person goes to at most one name: when two names claim the same person,
    the stronger rule keeps them and the other name is left unmatched, with the
    person in its review list.

    `confirmed` maps names to people already known to be them, for example
    after a person checked a suggestion; they are applied as "confirmed" and
    win any conflict. `rejected` holds (name, person) pairs known not to be the
    same, which are then neither applied nor suggested.
    """
    confirmed = confirmed or {}
    rejected = set(rejected)
    unknown = [p for p in confirmed.values() if p not in people]
    if unknown:
        raise ValueError(f"confirmed people not in `people`: {unknown}")
    twice = [p for p, n in Counter(confirmed.values()).items() if n > 1]
    if twice:
        raise ValueError(f"people confirmed for more than one name: {twice}")

    candidates = []
    for person, spellings in people.items():
        prepared = [_prepare(s) for s in spellings]
        candidates.append((person, [s for s in prepared if s.parts]))

    found = {}
    for name in dict.fromkeys(names):
        query = _prepare(name)
        found[name] = []
        if query.parts and name not in confirmed:
            for person, spellings in candidates:
                if (name, person) in rejected:
                    continue
                hits = _hits(query, person, spellings)
                if hits:
                    found[name].append(hits)

    counts = Counter(names)
    matched, ambiguous = {}, {}
    for name, per_person in found.items():
        best = [hits[0] for hits in per_person if hits[0].rule in APPLIED]
        if best:
            tier = min(_tier(h.rule) for h in best)
            best = [h for h in best if _tier(h.rule) == tier]
        if counts[name] > 1 or len(best) > 1:
            ambiguous[name] = best
        elif name in confirmed:
            person = confirmed[name]
            matched[name] = Hit(person, "confirmed", next(iter(people[person]), ""))
        elif best:
            matched[name] = best[0]

    claims = {}
    for name, hit in matched.items():
        claims.setdefault(hit.person, []).append(name)
    for claimants in claims.values():
        if len(claimants) < 2:
            continue
        tier = min(_tier(matched[n].rule) for n in claimants)
        winners = [n for n in claimants if _tier(matched[n].rule) == tier]
        for n in claimants:
            if n not in winners:
                del matched[n]
            elif len(winners) > 1:
                ambiguous[n] = [matched.pop(n)]

    unmatched = [n for n in found if n not in matched and n not in ambiguous]
    review = {}
    for n in unmatched:
        hits = sorted(
            (h for per_person in found[n] for h in per_person),
            key=lambda h: RULES.index(h.rule),
        )
        if hits:
            review[n] = hits
    return Result(matched, ambiguous, unmatched, review)
