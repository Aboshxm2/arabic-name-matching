"""Minimal xlsx reader/writer using only the Python standard library."""

import re
import zipfile
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _col_to_index(ref):
    letters = re.match(r"([A-Z]+)", ref).group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _index_to_col(idx):
    name = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        name = chr(65 + rem) + name
    return name


def _shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall("m:si", NS):
        strings.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    return strings


def sheet_names(path):
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("xl/workbook.xml"))
        return [s.get("name") for s in root.iter(f"{{{NS['m']}}}sheet")]


def read_sheet(path, sheet_index=0):
    """Return a list of rows; each row is a list of cell values as strings."""
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets = list(wb.iter(f"{{{NS['m']}}}sheet"))
        rid = sheets[sheet_index].get(f"{{{NS['r']}}}id")

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.get("Id") == rid:
                target = rel.get("Target")
        if target is None:
            target = f"worksheets/sheet{sheet_index + 1}.xml"
        if not target.startswith("/"):
            target = "xl/" + target.lstrip("/")
        else:
            target = target.lstrip("/")

        root = ET.fromstring(zf.read(target))

    rows = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        cells = []
        for c in row.findall("m:c", NS):
            ref = c.get("r") or ""
            col = _col_to_index(ref) if ref else len(cells)
            while len(cells) < col:
                cells.append("")

            ctype = c.get("t")
            if ctype == "inlineStr":
                is_el = c.find("m:is", NS)
                value = "".join(t.text or "" for t in is_el.iter(f"{{{NS['m']}}}t")) if is_el is not None else ""
            else:
                v = c.find("m:v", NS)
                value = v.text if v is not None and v.text is not None else ""
                if ctype == "s" and value != "":
                    value = shared[int(value)]
            cells.append(value)
        rows.append(cells)
    return rows


def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Style ids usable in the `styles` mapping passed to write_sheet.
PLAIN, HEADER, BOLD, PRESENT, ABSENT, TITLE, CELL, PERCENT = range(8)

# Highlight ids usable in the `highlights` passed to write_sheet.
GOOD, BAD = range(2)


def ref(row, col):
    """A1-style reference for 0-based coordinates."""
    return f"{_index_to_col(col)}{row + 1}"


def span(row0, col0, row1, col1):
    """A1-style range for 0-based inclusive coordinates."""
    return f"{ref(row0, col0)}:{ref(row1, col1)}"


class Formula:
    """A cell formula (without the leading '=') with its precomputed value."""

    def __init__(self, expr, value):
        self.expr = expr
        self.value = value


def _cell_xml(cell_ref, value, style):
    if isinstance(value, Formula):
        if isinstance(value.value, (int, float)):
            return f'<c r="{cell_ref}"{style}><f>{_esc(value.expr)}</f><v>{value.value}</v></c>'
        return f'<c r="{cell_ref}" t="str"{style}><f>{_esc(value.expr)}</f><v>{_esc(value.value)}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{cell_ref}"{style}><v>{value}</v></c>'
    return f'<c r="{cell_ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_esc(value)}</t></is></c>'


def _sheet_xml(
    rows,
    rtl=True,
    widths=None,
    styles=None,
    autofilter=None,
    choices=None,
    highlights=None,
    freeze=None,
):
    """The worksheet XML for rows (list of lists).

    Cell values may be str, int/float, or Formula.
    styles maps (row, col) 0-based coordinates to one of the style ids above.
    autofilter is a range (see span) that gets sort/filter buttons on its first row.
    choices is a list of (range, [allowed values]) shown as a dropdown.
    highlights is a list of (range, {value: GOOD or BAD}) applied as conditional
    formatting, so the colour follows the cell when it is edited.
    freeze is (rows, cols) to keep in view while scrolling.
    """
    styles = styles or {}
    sheet_rows = []
    for r_i, row in enumerate(rows):
        cells = []
        for c_i, value in enumerate(row):
            s = styles.get((r_i, c_i), PLAIN)
            style = f' s="{s}"' if s else ""
            cells.append(_cell_xml(ref(r_i, c_i), value, style))
        sheet_rows.append(f'<row r="{r_i + 1}">{"".join(cells)}</row>')

    cols_xml = ""
    if widths:
        cols = "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)
        )
        cols_xml = f"<cols>{cols}</cols>"

    sheet_view = '<sheetView workbookViewId="0"'
    sheet_view += ' rightToLeft="1"' if rtl else ""
    if freeze:
        f_rows, f_cols = freeze
        pane = "bottomRight" if f_rows and f_cols else ("bottomLeft" if f_rows else "topRight")
        sheet_view += (
            f'><pane xSplit="{f_cols}" ySplit="{f_rows}" topLeftCell="{ref(f_rows, f_cols)}"'
            f' activePane="{pane}" state="frozen"/></sheetView>'
        )
    else:
        sheet_view += "/>"

    filter_xml = f'<autoFilter ref="{autofilter}"/>' if autofilter else ""

    cf_xml = ""
    priority = 1
    for rng, rules in highlights or []:
        cf_rules = ""
        for text, dxf in rules.items():
            cf_rules += (
                f'<cfRule type="cellIs" dxfId="{dxf}" priority="{priority}" operator="equal">'
                f"<formula>{_esc(chr(34) + text + chr(34))}</formula></cfRule>"
            )
            priority += 1
        cf_xml += f'<conditionalFormatting sqref="{rng}">{cf_rules}</conditionalFormatting>'

    dv_xml = ""
    if choices:
        dvs = "".join(
            f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{rng}">'
            f"<formula1>{_esc(chr(34) + ','.join(values) + chr(34))}</formula1></dataValidation>"
            for rng, values in choices
        )
        dv_xml = f'<dataValidations count="{len(choices)}">{dvs}</dataValidations>'

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetViews>{sheet_view}</sheetViews>"
        f"{cols_xml}"
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        f"{filter_xml}{cf_xml}{dv_xml}"
        "</worksheet>"
    )

    return sheet_xml


def write_sheet(path, rows, sheet_name="Sheet1", **options):
    """Write rows (list of lists) to a one-sheet xlsx file; see _sheet_xml for options."""
    write_workbook(path, [dict(options, name=sheet_name, rows=rows)])


def write_workbook(path, sheets):
    """Write several sheets to one xlsx file.

    Each sheet is a dict with "name" and "rows", plus any of _sheet_xml's
    options (rtl, widths, styles, autofilter, choices, highlights, freeze).
    Sheet names must be unique, at most 31 characters, and free of []:*?/\\.
    """
    names = [sh["name"] for sh in sheets]
    for name in names:
        if len(name) > 31 or re.search(r"[\[\]:*?/\\]", name):
            raise ValueError(f"invalid sheet name: {name!r}")
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate sheet names: {names}")

    sheet_xmls = []
    defined = ""
    for i, sh in enumerate(sheets):
        options = {k: v for k, v in sh.items() if k not in ("name", "rows")}
        sheet_xmls.append(_sheet_xml(sh["rows"], **options))
        autofilter = sh.get("autofilter")
        if autofilter:
            absolute = "$" + autofilter.replace(":", ":$")
            absolute = re.sub(r"([A-Z]+)(\d+)", r"\1$\2", absolute)
            sheet_ref = "'" + sh["name"].replace("'", "''") + "'"
            defined += (
                f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                f"{_esc(sheet_ref)}!{absolute}</definedName>"
            )
    defined_names = f"<definedNames>{defined}</definedNames>" if defined else ""
    sheet_entries = "".join(
        f'<sheet name="{_esc(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, name in enumerate(names)
    )
    styles_id = len(sheets) + 1

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_entries}</sheets>"
        f"{defined_names}"
        '<calcPr calcId="191029" fullCalcOnLoad="1"/>'
        "</workbook>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="6">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '<font><sz val="11"/><color rgb="FF0B6623"/><name val="Calibri"/></font>'
        '<font><sz val="11"/><color rgb="FF9C0006"/><name val="Calibri"/></font>'
        '<font><b/><sz val="14"/><color rgb="FF1F3864"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="6">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF2F5597"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF2F2F2"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="2">'
        "<border><left/><right/><top/><bottom/><diagonal/></border>"
        '<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right>'
        '<top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border>'
        "</borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="8">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="4" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="5" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="9" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        "</cellXfs>"
        '<dxfs count="2">'
        '<dxf><font><color rgb="FF0B6623"/></font><fill><patternFill><bgColor rgb="FFC6EFCE"/></patternFill></fill></dxf>'
        '<dxf><font><color rgb="FF9C0006"/></font><fill><patternFill><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf>'
        "</dxfs>"
        "</styleSheet>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(len(sheets))
        )
        +         '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
            for i in range(len(sheets))
        )
        + f'<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/styles.xml", styles_xml)
        for i, sheet_xml in enumerate(sheet_xmls):
            zf.writestr(f"xl/worksheets/sheet{i + 1}.xml", sheet_xml)
