# Word Counter

Section-aware word counter for Markdown files. Counts words per heading, table, caption, references, and named sections (Abstract, Introduction, Methodology, etc.).

## Folder structure

```
word-counter/
├── word_counter.py     ← the script
├── files/              ← drop your .md files here
├── output/             ← reports are saved here (gitignored)
├── README.md
└── .gitignore
```

## Setup

**Requirements:** Python 3.8+

```bash
pip install rich
```

> `rich` is optional — without it the terminal output falls back to plain text. Everything else uses the Python standard library.

## Usage

1. Drop your `.md` files into the `files/` folder
2. Run:

```bash
python word_counter.py
```

## Output

Every run produces:

| Output | Location | Description |
|---|---|---|
| Terminal table | Console | Colour-coded per section type |
| Per-file CSV | `output/<name>_wordcount.csv` | One row per section |
| Combined report | `output/summary_report.txt` | All files in one readable file |

## What it detects

| Element | Label |
|---|---|
| Document title (H1) | `H1 · <Title>` |
| Subheadings (H2–H6) | `H2 · Introduction`, `H3 · Data Collection`, etc. |
| Named sections | Abstract, Methodology, Results, Conclusion, References, etc. |
| Tables | `[Table]` |
| Captions | `[Caption]` — lines starting with *Figure*, *Table*, *Chart* |
| Reference lists | `[References]` — numbered refs, author-year, URLs |
| Body text | counted under the preceding heading |

## Works well with

[markitdown-generator](https://github.com/muryithe/markitdown-generator) — converts PDFs and Word docs to Markdown first, then drop the `.md` files into `files/` here.
