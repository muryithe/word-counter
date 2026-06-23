#!/usr/bin/env python3
"""
word_counter.py
---------------
Counts words in .md files (markitdown output).

Logic:
  - Everything under an H1 is rolled up into that H1 section
  - Tables and Figures are tracked separately with their own counts
  - Output is one clean page:
      1. Summary (file totals)
      2. Per H1 section word count (body prose only)
      3. Tables & Figures inventory

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
    from reportlab.lib.enums import TA_RIGHT
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

# ── regex helpers ─────────────────────────────────────────────────────────────
REF_LINE_RE  = re.compile(
    r'^\s*(\[?\d+\]?[\.\)]\s|[A-Z][a-z]+,\s[A-Z][\.\,].*\(\d{4}\)|https?://)',
    re.IGNORECASE
)
TABLE_SEP_RE = re.compile(r'^\s*\|[\s\-\|:]+\|\s*$')
CAPTION_RE   = re.compile(
    r'^\s*(figure|fig\.?|table|tbl\.?|chart|graph|image|photo|plate)\s*(\d+[\.\:]?)?',
    re.IGNORECASE
)


def clean(text: str) -> str:
    text = re.sub(r'\{#[^}]*\}', '', text)       # {#anchor}
    text = re.sub(r'<[^>]+>', '', text)            # HTML tags
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)  # [text](url)
    text = re.sub(r'[*_~`]', '', text)             # bold/italic
    text = re.sub(r'https?://\S+', '', text)       # URLs
    text = re.sub(r'[#>|\\]', ' ', text)
    return text.strip()

def wc(text: str) -> int:
    t = clean(text)
    return len(t.split()) if t else 0

def clean_label(text: str) -> str:
    text = re.sub(r'\{#[^}]*\}', '', text)
    text = re.sub(r'[*_`]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ── named section detection ───────────────────────────────────────────────────
REFERENCES_RE = re.compile(
    r'^(references|bibliography|works cited|reference list)$', re.IGNORECASE
)

# ── parse ─────────────────────────────────────────────────────────────────────
def parse(path: Path):
    """
    Counts:
      - h1_sections : body prose only (tables excluded, refs counted separately)
      - tables      : pipe-table content + captions, keyed by label
      - ref_words   : total words in the References H1 section (full list)

    Grand total = body_total (excl. refs) + ref_words + table_total
    The References section is shown in the H1 table with its true count.
    """
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()

    h1_sections     = []        # ordered list of H1 names
    h1_words        = {}        # name -> prose word count
    tables          = []        # [{label, words}]

    current_h1      = None
    in_refs_section = False     # True when inside the References H1
    in_code         = False
    in_table        = False
    pending_caption = None

    def add_prose(n):
        """Add n words to current H1 body (never called during table or refs)."""
        if current_h1 is not None:
            h1_words[current_h1] = h1_words.get(current_h1, 0) + n

    for line in lines:
        stripped = line.strip()

        # ── skip code blocks ──────────────────────────────────────────────────
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_code = not in_code; continue
        if in_code: continue

        # ── skip markitdown metadata ──────────────────────────────────────────
        if stripped.startswith('<!--'): continue

        # ── skip table separator rows |---|---| ───────────────────────────────
        if TABLE_SEP_RE.match(line): continue

        # ── pipe-table rows ───────────────────────────────────────────────────
        if re.match(r'^\s*\|', line):
            if not in_table:
                in_table = True
                tables.append({'label': pending_caption or '[Table]',
                               'words': 0,
                               'h1': current_h1})
                pending_caption = None
            tables[-1]['words'] += wc(re.sub(r'\|', ' ', line))
            continue
        else:
            in_table = False

        # ── headings ──────────────────────────────────────────────────────────
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            hashes, title = m.groups()
            level = len(hashes)
            title = clean_label(title)

            if level == 1:
                current_h1 = title
                in_refs_section = bool(REFERENCES_RE.match(title))
                if current_h1 not in h1_words:
                    h1_words[current_h1] = 0
                    h1_sections.append(current_h1)
            # heading text itself is not counted as body prose
            continue

        # ── caption lines ─────────────────────────────────────────────────────
        if CAPTION_RE.match(stripped):
            label = clean_label(stripped)
            if tables and tables[-1]['label'] == '[Table]':
                tables[-1]['label'] = label   # attach to previous table
            else:
                pending_caption = label       # attach to next table
            continue

        # ── reference-list lines (numbered / author-year / URL) ───────────────
        if REF_LINE_RE.match(stripped):
            # Count them — they belong to the References H1
            add_prose(wc(stripped))
            continue

        # ── body prose ────────────────────────────────────────────────────────
        if stripped:
            add_prose(wc(stripped))

    # ── build results ─────────────────────────────────────────────────────────
    result_h1   = [{'name': n, 'words': h1_words[n]} for n in h1_sections]
    body_total  = sum(s['words'] for s in result_h1)
    table_total = sum(t['words'] for t in tables)
    ref_total   = sum(s['words'] for s in result_h1 if REFERENCES_RE.match(s['name']))
    net_total   = body_total - table_total - ref_total   # prose only

    return result_h1, tables, body_total, table_total, ref_total, net_total


# ── terminal ──────────────────────────────────────────────────────────────────
def print_terminal(filename, h1s, tables, body_total, table_total, ref_total, net_total):
    if HAS_RICH:
        t = Table(title=f'[bold]{filename}[/] — Word Count by H1 Section (tables excluded)', box=box.SIMPLE_HEAD)
        t.add_column('Section', min_width=40)
        t.add_column('Words', justify='right')
        t.add_column('%', justify='right')
        for s in h1s:
            pct = round(s['words'] / body_total * 100, 1) if body_total else 0
            t.add_row(f"[cyan]{s['name']}[/]", f"{s['words']:,}", f"{pct}%")
        t.add_row('[bold]SECTION TOTAL[/]', f"[bold]{body_total:,}[/]", '[bold]100%[/]')
        console.print(t)

        if tables:
            t2 = Table(title='Tables & Figures', box=box.SIMPLE_HEAD)
            t2.add_column('Item', min_width=50)
            t2.add_column('Words', justify='right')
            for tb in tables:
                t2.add_row(f"[yellow]{tb['label']}[/]", f"{tb['words']:,}")
            t2.add_row('[bold]TABLE TOTAL[/]', f"[bold]{table_total:,}[/]")
            console.print(t2)

        console.print(f"  Tables:     [yellow]{table_total:,}[/]")
        console.print(f"  References: [dim green]{ref_total:,}[/]")
        console.print(f"  [bold green]NET WORD COUNT (sections − tables − references): {net_total:,}[/]\n")
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
        print(f"\n  Tables:     {table_total:,}")
        print(f"  References: {ref_total:,}")
        print(f"  NET WORD COUNT: {net_total:,}\n")


# ── PDF ───────────────────────────────────────────────────────────────────────
def make_pdf(all_results, out_path: Path):
    generated = datetime.now().strftime('%d %B %Y, %H:%M')
    n_files   = len(all_results)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MID_GREY)
        footer_text = f"Generated {generated}  ·  {n_files} file(s)  ·  Page {doc.page}"
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, footer_text)
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
        'title' : sty('T',  fontSize=20, textColor=BLUE,    spaceAfter=4,   fontName='Helvetica-Bold'),
        'meta'  : sty('M',  fontSize=9,  textColor=MID_GREY, spaceAfter=14, fontName='Helvetica'),
        'h2'    : sty('H2', fontSize=12, textColor=BLUE,    spaceBefore=16, spaceAfter=5, fontName='Helvetica-Bold'),
        'h3'    : sty('H3', fontSize=10, textColor=colors.HexColor('#333333'),
                       spaceBefore=10, spaceAfter=3, fontName='Helvetica-Bold'),
        'cell'  : sty('C',  fontSize=9,  fontName='Helvetica', leading=12),
        'cell_b': sty('CB', fontSize=9,  fontName='Helvetica-Bold', leading=12),
        'cell_r': sty('CR', fontSize=9,  fontName='Helvetica', leading=12, alignment=TA_RIGHT),
        'cell_rb':sty('CRB',fontSize=9,  fontName='Helvetica-Bold', leading=12, alignment=TA_RIGHT),
    }

    def p(txt, st='cell'):   return Paragraph(str(txt), S[st])
    def pr(txt, bold=False): return Paragraph(str(txt), S['cell_rb' if bold else 'cell_r'])
    def sp(h=0.25):          return Spacer(1, h*cm)
    def hr():                return HRFlowable(width='100%', thickness=0.4,
                                               color=colors.HexColor('#CCCCCC'), spaceAfter=4)

    def tstyle(n, has_total=True):
        cmds = [
            ('BACKGROUND',   (0,0), (-1,0),  BLUE),
            ('TEXTCOLOR',    (0,0), (-1,0),  WHITE),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS',(0,1),(-1,-2 if has_total else -1),
             [WHITE, colors.HexColor('#F7F7F7')]),
            ('GRID',         (0,0), (-1,-1), 0.3, colors.HexColor('#DDDDDD')),
            ('LEFTPADDING',  (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING',   (0,0), (-1,-1), 3),
            ('BOTTOMPADDING',(0,0), (-1,-1), 3),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ]
        if has_total:
            cmds += [
                ('BACKGROUND', (0,-1), (-1,-1), LIGHT_GREY),
                ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
                ('LINEABOVE',  (0,-1), (-1,-1), 0.8, BLUE),
            ]
        return TableStyle(cmds)

    story = []

    story += [
        Paragraph('Word Count Report', S['title']),
        hr(), sp(0.3),
    ]

    # ── 1. File summary ───────────────────────────────────────────────────────
    story.append(Paragraph('File Summary', S['h2']))
    story.append(sp(0.15))

    grand_body  = sum(r['body_total']  for r in all_results)
    grand_table = sum(r['table_total'] for r in all_results)
    grand_ref   = sum(r['ref_total']   for r in all_results)
    grand_net   = sum(r['net_total']   for r in all_results)

    sum_data = [[p('File','cell_b'), p('All Sections','cell_b'),
                 p('− Tables','cell_b'), p('− References','cell_b'), p('Net Words','cell_b')]]
    for res in all_results:
        sum_data.append([
            p(res['filename']),
            pr(f"{res['body_total']:,}"),
            pr(f"{res['table_total']:,}"),
            pr(f"{res['ref_total']:,}"),
            pr(f"{res['net_total']:,}", bold=True),
        ])
    sum_data.append([
        p('TOTAL', 'cell_b'),
        pr(f"{grand_body:,}", bold=True),
        pr(f"{grand_table:,}", bold=True),
        pr(f"{grand_ref:,}", bold=True),
        pr(f"{grand_net:,}", bold=True),
    ])
    story.append(RLTable(sum_data,
        colWidths=[W*0.36, W*0.16, W*0.16, W*0.16, W*0.16],
        style=tstyle(len(sum_data)), repeatRows=1))
    story += [sp(0.4), hr(), sp(0.3)]

    # ── per-file detail ───────────────────────────────────────────────────────
    for res in all_results:
        story.append(Paragraph(res['filename'], S['h3']))
        story.append(sp(0.1))

        # ── 2. H1 section body count ──────────────────────────────────────────
        story.append(Paragraph('Word Count by H1 Section (tables excluded)', S['h2']))
        story.append(sp(0.1))

        bt = res['body_total']
        sec_data = [[p('Section','cell_b'), p('Words','cell_b'), p('%','cell_b')]]
        for s in res['h1s']:
            pct = round(s['words'] / bt * 100, 1) if bt else 0
            sec_data.append([p(s['name']), pr(f"{s['words']:,}"), pr(f"{pct}%")])
        sec_data.append([p('BODY TOTAL','cell_b'), pr(f"{bt:,}", bold=True), pr('100%', bold=True)])

        story.append(RLTable(sec_data,
            colWidths=[W*0.64, W*0.18, W*0.18],
            style=tstyle(len(sec_data)), repeatRows=1))
        story += [sp(0.3)]

        # ── 3. Tables & Figures ───────────────────────────────────────────────
        if res['tables']:
            story.append(Paragraph('Tables & Figures', S['h2']))
            story.append(sp(0.1))

            tt = res['table_total']
            tbl_data = [[p('Item','cell_b'), p('Words','cell_b'), p('%','cell_b')]]
            for tb in res['tables']:
                pct = round(tb['words'] / tt * 100, 1) if tt else 0
                tbl_data.append([p(tb['label']), pr(f"{tb['words']:,}"), pr(f"{pct}%")])
            tbl_data.append([p('TABLE TOTAL','cell_b'), pr(f"{tt:,}", bold=True), pr('100%', bold=True)])

            story.append(RLTable(tbl_data,
                colWidths=[W*0.64, W*0.18, W*0.18],
                style=tstyle(len(tbl_data)), repeatRows=1))
            story += [sp(0.3)]

        story += [hr(), sp(0.3)]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"  Saved → output/report.pdf")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    OUT.mkdir(exist_ok=True)
    md_files = sorted(FILES.glob('*.md'))
    if not md_files:
        print(f'No .md files in {FILES}. Drop files there and re-run.')
        sys.exit(0)

    print(f'\nFound {len(md_files)} file(s) in files/\n')

    all_results = []
    for md in md_files:
        h1s, tables, body_total, table_total, ref_total, net_total = parse(md)
        print_terminal(md.name, h1s, tables, body_total, table_total, ref_total, net_total)
        all_results.append({
            'filename'   : md.name,
            'h1s'        : h1s,
            'tables'     : tables,
            'body_total' : body_total,
            'table_total': table_total,
            'ref_total'  : ref_total,
            'net_total'  : net_total,
        })

    if not all_results:
        print('No content extracted.'); sys.exit(0)

    if HAS_PDF:
        make_pdf(all_results, OUT / 'report.pdf')
    else:
        print("Install reportlab to get PDF output: pip install reportlab")
    print()

if __name__ == '__main__':
    main()