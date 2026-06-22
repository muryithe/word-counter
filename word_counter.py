#!/usr/bin/env python3
"""
word_counter.py
---------------
Counts words per section in all .md files inside the `files/` folder.
Distinguishes titles, subheadings, body text, tables, captions,
references, footnotes, and named sections (Abstract, Introduction, etc.)

Output:
  - Terminal table (always shown)
  - output/report.md  (full report with all files, rendered as Markdown)

Usage:
    python word_counter.py
"""

import re
import sys
from pathlib import Path

# ── optional rich for pretty terminal tables ─────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

# ── paths ────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent
FILES    = ROOT / "files"
OUTPUT   = ROOT / "output"

# ── named sections ───────────────────────────────────────────────────────────
NAMED_SECTIONS = [
    "abstract", "summary", "executive summary",
    "introduction", "background", "context",
    "literature review", "related work", "theoretical framework",
    "methodology", "methods", "research design", "approach",
    "results", "findings", "analysis", "discussion",
    "conclusion", "conclusions", "recommendations",
    "acknowledgements", "acknowledgments",
    "references", "bibliography", "works cited",
    "appendix", "appendices", "annexure", "annex",
    "glossary", "abbreviations", "acronyms",
    "table of contents", "list of figures", "list of tables",
]

REF_LINE_RE = re.compile(
    r'^\s*(\[?\d+\]?\.?\s|[A-Z][a-z]+,\s[A-Z]\..*\(\d{4}\)|https?://)',
    re.IGNORECASE
)
CAPTION_RE = re.compile(
    r'^\s*(figure|fig\.?|table|chart|graph|image|photo|plate)\s*\d*[:\.]',
    re.IGNORECASE
)


# ═══════════════════════════════════════════════════════════════════════════
class Section:
    def __init__(self, label: str, section_type: str):
        self.label = label
        self.section_type = section_type
        self.words = 0


def count_words(text: str) -> int:
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_`#~>|\\]', ' ', text)
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)
    return len(text.split())


def classify_named(heading: str):
    h = heading.lower().strip()
    for name in NAMED_SECTIONS:
        if h == name or h.startswith(name):
            return name.title()
    return None


# ═══════════════════════════════════════════════════════════════════════════
def parse_markdown(path: Path):
    lines    = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    sections = []
    current  = None
    in_code  = False
    in_table = False

    def push(s):
        nonlocal current
        if current:
            sections.append(current)
        current = s

    for line in lines:
        # code fences
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue

        # html comments (markitdown metadata)
        if line.strip().startswith("<!--"):
            continue

        # table rows
        if re.match(r'^\s*\|', line):
            if not in_table:
                in_table = True
                push(Section("[Table]", "table"))
            current.words += count_words(re.sub(r'\|', ' ', line))
            continue
        else:
            in_table = False

        # ATX headings
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            hashes, title = m.groups()
            level  = len(hashes)
            title  = title.strip()
            named  = classify_named(title)
            htype  = "title" if level == 1 else f"h{level}"
            label  = f"{'H'+str(level)} · {named or title}"
            push(Section(label, htype))
            continue

        # setext headings
        if re.match(r'^[=]{3,}\s*$', line) and current:
            current.section_type = "title"
            continue
        if re.match(r'^[-]{3,}\s*$', line) and current:
            current.section_type = "h2"
            continue

        # caption
        if CAPTION_RE.match(line):
            push(Section("[Caption]", "caption"))
            current.words += count_words(line)
            continue

        # reference list line
        if REF_LINE_RE.match(line):
            if current and current.section_type == "reference":
                current.words += count_words(line)
            elif sections and sections[-1].section_type == "reference":
                sections[-1].words += count_words(line)
            else:
                push(Section("[References]", "reference"))
                current.words += count_words(line)
            continue

        # body text
        stripped = line.strip()
        if stripped:
            if current is None:
                push(Section("[Preamble]", "body"))
            current.words += count_words(stripped)

    if current:
        sections.append(current)

    return sections


# ═══════════════════════════════════════════════════════════════════════════
def build_rows(sections):
    """Returns list of (label, type, words, pct) plus a TOTAL row."""
    total = sum(s.words for s in sections)
    rows  = []
    for s in sections:
        if s.words == 0:
            continue
        pct = round(s.words / total * 100, 1) if total else 0
        rows.append((s.label, s.section_type, s.words, pct))
    rows.append(("TOTAL", "—", total, 100.0))
    return rows


# ═══════════════════════════════════════════════════════════════════════════
TYPE_COLOURS = {
    "title":     "bold cyan",
    "h1":        "bold cyan",
    "h2":        "cyan",
    "h3":        "bright_cyan",
    "body":      "white",
    "table":     "yellow",
    "caption":   "magenta",
    "footnote":  "dim white",
    "reference": "dim green",
    "—":         "bold white",
}


def print_terminal(filename: str, rows):
    if HAS_RICH:
        t = Table(title=f"Word Count · {filename}", box=box.SIMPLE_HEAD, show_lines=False)
        t.add_column("Section",  style="white", no_wrap=False, min_width=40)
        t.add_column("Type",     style="dim",   min_width=10)
        t.add_column("Words",    justify="right")
        t.add_column("%",        justify="right")
        for label, stype, words, pct in rows:
            c = TYPE_COLOURS.get(stype, "white")
            t.add_row(
                f"[{c}]{label}[/]",
                f"[{c}]{stype}[/]",
                f"[{'bold' if stype=='—' else c}]{words:,}[/]",
                f"[{c}]{pct}%[/]",
            )
        console.print(t)
    else:
        print(f"\n{'='*70}")
        print(f"  Word Count: {filename}")
        print(f"{'='*70}")
        print(f"  {'Section':<42} {'Type':<12} {'Words':>7}  {'%':>6}")
        print(f"  {'-'*68}")
        for label, stype, words, pct in rows:
            print(f"  {label:<42} {stype:<12} {words:>7,}  {pct:>5.1f}%")
        print()


def build_md_report(all_results: list) -> str:
    """Build a full Markdown report for all processed files."""
    from datetime import datetime
    lines = []

    lines.append("# Word Count Report\n")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    lines.append(f"_Files analysed: {len(all_results)}_\n")
    lines.append("\n---\n")

    # Overall summary table (one row per file, totals only)
    lines.append("## Summary\n")
    lines.append("| File | Total Words |")
    lines.append("|---|---:|")
    grand_total = 0
    for filename, rows in all_results:
        total_row = next(r for r in rows if r[1] == "—")
        lines.append(f"| {filename} | {total_row[2]:,} |")
        grand_total += total_row[2]
    lines.append(f"| **Grand Total** | **{grand_total:,}** |")
    lines.append("\n---\n")

    # Per-file detailed tables
    lines.append("## Detailed Breakdown\n")
    for filename, rows in all_results:
        lines.append(f"### {filename}\n")
        lines.append("| Section | Type | Words | % |")
        lines.append("|---|---|---:|---:|")
        for label, stype, words, pct in rows:
            if stype == "—":
                lines.append(f"| **TOTAL** | **—** | **{words:,}** | **{pct}%** |")
            else:
                lines.append(f"| {label} | {stype} | {words:,} | {pct}% |")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
def main():
    OUTPUT.mkdir(exist_ok=True)

    md_files = sorted(FILES.glob("*.md"))
    if not md_files:
        print(f"No .md files found in: {FILES}")
        print("Drop your markdown files into the `files/` folder and re-run.")
        sys.exit(0)

    print(f"\nFound {len(md_files)} file(s) in {FILES.name}/\n")

    all_results = []

    for md in md_files:
        sections = parse_markdown(md)
        if not sections:
            print(f"  [warn] No content extracted from {md.name}")
            continue

        rows = build_rows(sections)
        all_results.append((md.name, rows))

        # Terminal
        print_terminal(md.name, rows)

    # Save single MD report
    if all_results:
        report_path = OUTPUT / "report.md"
        report_path.write_text(build_md_report(all_results), encoding="utf-8")
        print(f"  Saved report → output/report.md\n")


if __name__ == "__main__":
    main()