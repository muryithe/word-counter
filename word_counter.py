#!/usr/bin/env python3
"""
word_counter.py
---------------
Counts words in .md files (markitdown output).

Rules:
  - H1 headings define top-level sections; all content beneath rolls up into them
  - H4 headings are treated as captions/labels for the nearest table or figure
  - Tables (pipe rows) are tracked separately under their H4 caption
  - In-text citations like (Smith, 2019) ARE counted as prose
  - The References H1 section word count is tracked so it can be deducted
  - Net count = all H1 section words − table words − reference section words
  - One PDF report per input file, saved as output/<stem>_report.pdf

Usage:
    python word_counter.py
"""

import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        Table as RLTable, TableStyle, HRFlowable
    )
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("[warn] reportlab not installed. Run: pip install reportlab")

ROOT  = Path(__file__).parent
FILES = ROOT / "files"
OUT   = ROOT / "output"

BLUE       = colors.HexColor('#2E75B6') if HAS_PDF else None
LIGHT_GREY = colors.HexColor('#F2F2F2') if HAS_PDF else None
MID_GREY   = colors.HexColor('#666666') if HAS_PDF else None
WHITE      = colors.white if HAS_PDF else None

REFERENCES_RE = re.compile(
    r'^(references|bibliography|works cited|reference list)s?$', re.IGNORECASE
)
TABLE_SEP_RE = re.compile(r'^\s*\|[\s\-\|:]+\|\s*$')

# ── ATX heading:  ## Title {#anchor}
ATX_RE = re.compile(r'^(#{1,6})\s+(.*)')
# ── HTML heading: <h1>Title</h1>  or  <h2 id="x">Title</h2>
HTML_H_RE = re.compile(r'^<h([1-6])[^>]*>(.*?)</h\1>', re.IGNORECASE)

# Known section names for implicit heading detection (plain-text PDFs)
KNOWN_SECTIONS = {
    "abstract", "acknowledgements", "acknowledgments", "preface",
    "introduction", "background", "context",
    "literature review", "review of literature", "related work", "theoretical framework",
    "conceptual framework", "theoretical background",
    "methodology", "methods", "research methodology", "research design",
    "research methods", "method", "approach",
    "findings", "results", "data analysis", "analysis",
    "discussion", "findings and discussion",
    "conclusion", "conclusions", "concluding remarks", "closing remarks",
    "recommendations",
    "references", "bibliography", "works cited", "reference list",
    "appendix", "appendices", "annexure", "annex",
    "glossary", "abbreviations", "list of figures", "list of tables",
    "table of contents", "contents",
    "declaration", "ethics statement", "consent",
    "limitations", "limitations and future research",
    "contributions", "implications",
    "executive summary", "summary",
}

def is_implicit_heading(stripped: str, prev_blank: bool, next_blank: bool) -> bool:
    """
    Detect section headings in plain-text PDFs that have no # markers.
    A line is treated as a section heading if:
      - it matches a known section name, OR
      - it's short (≤6 words), preceded by a blank line, not ending in punctuation,
        and not a sentence fragment
    """
    if not stripped:
        return False
    # Must be preceded by blank line
    if not prev_blank:
        return False
    # Must not end with sentence-ending punctuation or be a URL
    if stripped[-1] in '.,:;!?' or stripped.startswith('http'):
        return False
    # Must not contain digits mid-line (likely a sentence with a year/number)
    cleaned = clean(stripped)
    if not cleaned:
        return False
    words = cleaned.split()
    # Direct match against known sections (case-insensitive)
    if cleaned.lower() in KNOWN_SECTIONS:
        return True
    # Also match multi-word partial starts like "Literature Review and Analysis"
    for name in KNOWN_SECTIONS:
        if cleaned.lower().startswith(name) and len(words) <= 6:
            return True
    return False


def clean(text: str) -> str:
    """Strip markdown/HTML artifacts before word counting."""
    text = re.sub(r'\{#[^}]*\}', '', text)             # {#anchor-id}
    text = re.sub(r'<[^>]+>', '', text)                 # HTML tags
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)  # [text](url) → text
    text = re.sub(r'[*_~`]', '', text)                  # bold/italic markers
    text = re.sub(r'https?://\S+', '', text)            # bare URLs
    text = re.sub(r'[#>|\\]', ' ', text)
    return text.strip()

def wc(text: str) -> int:
    t = clean(text)
    return len(t.split()) if t else 0

def clean_label(text: str) -> str:
    text = re.sub(r'\{#[^}]*\}', '', text)
    text = re.sub(r'[*_`]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_heading(line: str):
    """Return (level, title) or None. Handles ATX (#) and HTML (<h1>) styles."""
    m = ATX_RE.match(line)
    if m:
        return len(m.group(1)), clean_label(m.group(2))
    m = HTML_H_RE.match(line.strip())
    if m:
        return int(m.group(1)), clean_label(m.group(2))
    return None


# ── parse ─────────────────────────────────────────────────────────────────────
def parse(path: Path):
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()

    h1_sections  = []
    h1_words     = {}
    tables       = []

    current_h1   = None
    in_code      = False
    in_table     = False
    pending_h4   = None
    has_any_md_headings = False  # track whether file uses # headings

    # Pre-scan: does this file have any ATX or HTML headings?
    for line in lines:
        if ATX_RE.match(line) or HTML_H_RE.match(line.strip()):
            has_any_md_headings = True
            break

    def add_prose(n):
        if current_h1 is not None and n > 0:
            h1_words[current_h1] = h1_words.get(current_h1, 0) + n

    def set_h1(title):
        nonlocal current_h1, pending_h4
        current_h1 = title
        if current_h1 not in h1_words:
            h1_words[current_h1] = 0
            h1_sections.append(current_h1)
        pending_h4 = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # ── code fences ───────────────────────────────────────────────────────
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_code = not in_code; continue
        if in_code: continue

        # ── markitdown metadata comments ──────────────────────────────────────
        if stripped.startswith('<!--') and stripped.endswith('-->'):
            continue

        # ── table separator  |---|---| ────────────────────────────────────────
        if TABLE_SEP_RE.match(line):
            continue

        # ── pipe-table data rows ──────────────────────────────────────────────
        if re.match(r'^\s*\|', line):
            if not in_table:
                in_table = True
                label = pending_h4 or '[Table]'
                pending_h4 = None
                tables.append({'label': label, 'words': 0})
            tables[-1]['words'] += wc(re.sub(r'\|', ' ', line))
            continue
        else:
            in_table = False

        # ── explicit headings (ATX # or HTML <h1>) ────────────────────────────
        heading = parse_heading(line)
        if heading:
            level, title = heading
            if level == 1:
                set_h1(title)
            elif level == 4:
                pending_h4 = title
            continue

        # ── implicit headings (plain-text PDFs with no # markers) ─────────────
        if not has_any_md_headings and stripped:
            prev_blank = (i == 0) or (lines[i-1].strip() == '')
            next_blank = (i == len(lines)-1) or (lines[i+1].strip() == '')
            if is_implicit_heading(stripped, prev_blank, next_blank):
                set_h1(clean_label(stripped))
                continue

        # ── body prose ────────────────────────────────────────────────────────
        if stripped:
            add_prose(wc(stripped))

    # ── aggregate ─────────────────────────────────────────────────────────────
    result_h1   = [{'name': n, 'words': h1_words[n]} for n in h1_sections]
    body_total  = sum(s['words'] for s in result_h1)
    table_total = sum(t['words'] for t in tables)
    ref_total   = sum(s['words'] for s in result_h1
                      if REFERENCES_RE.match(s['name']))
    net_total   = body_total - table_total - ref_total

    return result_h1, tables, body_total, table_total, ref_total, net_total


# ── terminal ──────────────────────────────────────────────────────────────────
def print_terminal(filename, h1s, tables, body_total, table_total, ref_total, net_total):
    if HAS_RICH:
        t = Table(title=f'[bold]{filename}[/]', box=box.SIMPLE_HEAD)
        t.add_column('H1 Section', min_width=40)
        t.add_column('Words', justify='right')
        t.add_column('%', justify='right')
        for s in h1s:
            pct = round(s['words'] / body_total * 100, 1) if body_total else 0
            is_ref = bool(REFERENCES_RE.match(s['name']))
            colour = 'dim green' if is_ref else 'cyan'
            t.add_row(f"[{colour}]{s['name']}[/]", f"{s['words']:,}", f"{pct}%")
        t.add_row('[bold]SECTION TOTAL[/]', f"[bold]{body_total:,}[/]", '[bold]100%[/]')
        console.print(t)

        if tables:
            t2 = Table(title='Tables & Figures', box=box.SIMPLE_HEAD)
            t2.add_column('Caption (H4)', min_width=50)
            t2.add_column('Words', justify='right')
            for tb in tables:
                t2.add_row(f"[yellow]{tb['label']}[/]", f"{tb['words']:,}")
            t2.add_row('[bold]TABLE TOTAL[/]', f"[bold]{table_total:,}[/]")
            console.print(t2)

        console.print(f"  − Tables:     {table_total:,}")
        console.print(f"  − References: {ref_total:,}")
        console.print(f"  [bold green]NET WORD COUNT: {net_total:,}[/]\n")
    else:
        print(f"\n{'='*65}\n  {filename}\n{'='*65}")
        for s in h1s:
            pct = round(s['words'] / body_total * 100, 1) if body_total else 0
            print(f"  {s['name']:<45} {s['words']:>7,}  {pct:>5.1f}%")
        print(f"  {'SECTION TOTAL':<45} {body_total:>7,}")
        if tables:
            print()
            for tb in tables:
                print(f"  {tb['label']:<45} {tb['words']:>7,}")
        print(f"\n  − Tables:     {table_total:,}")
        print(f"  − References: {ref_total:,}")
        print(f"  NET WORD COUNT: {net_total:,}\n")


# ── PDF (one per file) ────────────────────────────────────────────────────────
def make_pdf(res, out_path: Path):
    generated = datetime.now().strftime('%d %B %Y, %H:%M')
    filename  = res['filename']

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MID_GREY)
        canvas.drawCentredString(
            A4[0] / 2, 1.2 * cm,
            f"{filename}  ·  Generated {generated}  ·  Page {doc.page}"
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    W = A4[0] - 4*cm

    base = getSampleStyleSheet()
    def sty(name, **kw):
        return ParagraphStyle(name, parent=base['Normal'], **kw)

    S = {
        'title' : sty('T',   fontSize=16, textColor=BLUE, spaceAfter=2,  fontName='Helvetica-Bold'),
        'fname' : sty('FN',  fontSize=9,  textColor=MID_GREY, spaceAfter=12, fontName='Helvetica'),
        'h2'    : sty('H2',  fontSize=11, textColor=BLUE, spaceBefore=14, spaceAfter=4, fontName='Helvetica-Bold'),
        'net'   : sty('NET', fontSize=11, textColor=BLUE, spaceBefore=8,  spaceAfter=4,
                       fontName='Helvetica-Bold', alignment=TA_CENTER),
        'cell'  : sty('C',   fontSize=9,  fontName='Helvetica', leading=12),
        'cell_b': sty('CB',  fontSize=9,  fontName='Helvetica-Bold', leading=12),
        'cell_r': sty('CR',  fontSize=9,  fontName='Helvetica', leading=12, alignment=TA_RIGHT),
        'cell_rb':sty('CRB', fontSize=9,  fontName='Helvetica-Bold', leading=12, alignment=TA_RIGHT),
    }

    def p(txt, st='cell'):   return Paragraph(str(txt), S[st])
    def pr(txt, bold=False): return Paragraph(str(txt), S['cell_rb' if bold else 'cell_r'])
    def sp(h=0.25):          return Spacer(1, h*cm)
    def hr():                return HRFlowable(width='100%', thickness=0.4,
                                               color=colors.HexColor('#CCCCCC'), spaceAfter=4)

    def tstyle(n, has_total=True):
        cmds = [
            ('BACKGROUND',    (0,0), (-1,0),  BLUE),
            ('TEXTCOLOR',     (0,0), (-1,0),  WHITE),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS',(0,1), (-1,-2 if has_total else -1),
             [WHITE, colors.HexColor('#F7F7F7')]),
            ('GRID',          (0,0), (-1,-1), 0.3, colors.HexColor('#DDDDDD')),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ]
        if has_total:
            cmds += [
                ('BACKGROUND', (0,-1), (-1,-1), LIGHT_GREY),
                ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
                ('LINEABOVE',  (0,-1), (-1,-1), 0.8, BLUE),
            ]
        return TableStyle(cmds)

    story = []

    # Title
    story += [
        p('Word Count Report', 'title'),
        p(filename, 'fname'),
        hr(), sp(0.2),
    ]

    # ── 1. H1 Section breakdown ───────────────────────────────────────────────
    story.append(p('Word Count by Section', 'h2'))
    story.append(sp(0.1))

    bt = res['body_total']
    sec_data = [[p('H1 Section','cell_b'), p('Words','cell_b'), p('%','cell_b')]]
    for s in res['h1s']:
        pct = round(s['words'] / bt * 100, 1) if bt else 0
        sec_data.append([p(s['name']), pr(f"{s['words']:,}"), pr(f"{pct}%")])
    sec_data.append([p('SECTION TOTAL','cell_b'), pr(f"{bt:,}", bold=True), pr('100%', bold=True)])

    story.append(RLTable(sec_data,
        colWidths=[W*0.64, W*0.18, W*0.18],
        style=tstyle(len(sec_data)), repeatRows=1))
    story += [sp(0.3)]

    # ── 2. Tables & Figures ───────────────────────────────────────────────────
    if res['tables']:
        story.append(p('Tables & Figures', 'h2'))
        story.append(sp(0.1))

        tt = res['table_total']
        tbl_data = [[p('Caption (H4)','cell_b'), p('Words','cell_b'), p('%','cell_b')]]
        for tb in res['tables']:
            pct = round(tb['words'] / tt * 100, 1) if tt else 0
            tbl_data.append([p(tb['label']), pr(f"{tb['words']:,}"), pr(f"{pct}%")])
        tbl_data.append([p('TABLE TOTAL','cell_b'), pr(f"{tt:,}", bold=True), pr('100%', bold=True)])

        story.append(RLTable(tbl_data,
            colWidths=[W*0.64, W*0.18, W*0.18],
            style=tstyle(len(tbl_data)), repeatRows=1))
        story += [sp(0.3)]

    # ── 3. Net count summary ──────────────────────────────────────────────────
    story.append(hr())
    story.append(sp(0.15))

    net_data = [
        [p('All section words','cell_b'),  pr(f"{res['body_total']:,}", bold=True)],
        [p('− Table words',    'cell'),    pr(f"−{res['table_total']:,}")],
        [p('− Reference words','cell'),    pr(f"−{res['ref_total']:,}")],
        [p('NET WORD COUNT',   'cell_b'),  pr(f"{res['net_total']:,}", bold=True)],
    ]
    net_style = TableStyle([
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LINEABOVE',     (0,-1), (-1,-1), 0.8, BLUE),
        ('BACKGROUND',    (0,-1), (-1,-1), LIGHT_GREY),
        ('FONTNAME',      (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR',     (0,-1), (-1,-1), BLUE),
    ])
    story.append(RLTable(net_data,
        colWidths=[W*0.72, W*0.28],
        style=net_style))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"  Saved → output/{out_path.name}")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    OUT.mkdir(exist_ok=True)
    md_files = sorted(FILES.glob('*.md'))
    if not md_files:
        print(f'No .md files in {FILES}. Drop files there and re-run.')
        sys.exit(0)

    print(f'\nFound {len(md_files)} file(s) in files/\n')

    for md in md_files:
        h1s, tables, body_total, table_total, ref_total, net_total = parse(md)
        res = {
            'filename'   : md.name,
            'h1s'        : h1s,
            'tables'     : tables,
            'body_total' : body_total,
            'table_total': table_total,
            'ref_total'  : ref_total,
            'net_total'  : net_total,
        }
        print_terminal(md.name, h1s, tables, body_total, table_total, ref_total, net_total)

        if HAS_PDF:
            out_path = OUT / f"{md.stem}_report.pdf"
            make_pdf(res, out_path)
        else:
            print("Install reportlab: pip install reportlab")

    print()

if __name__ == '__main__':
    main()