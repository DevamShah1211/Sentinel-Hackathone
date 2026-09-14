"""
Render the submission documents to PDF.

    python tools/export_docs_pdf.py                    # HLD + PRESENTATION
    python tools/export_docs_pdf.py --only HLD

Five of the seven evaluation areas are judged on documents rather than running
software, and the portal takes PDFs. The markdown is the source of truth; this
converts it without anyone hand-formatting a Word file at 2 a.m. and introducing
a discrepancy between what the document says and what the repository does.

No pandoc and no LaTeX on this machine, so the path is markdown -> styled HTML
-> headless Chrome's own print-to-PDF. Chrome is already a dependency (Playwright
drives it for the UI screenshots), its layout engine handles the wide tables
these documents are full of, and it needs no TeX distribution.

Printed light-on-white deliberately. The console is a dark product, but a
document that reaches a reviewer as a PDF will be read on a screen and quite
possibly printed, and dark backgrounds waste toner and read badly on paper.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import markdown  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "DOCS"
OUT = ROOT / "submission"

TARGETS = {
    "HLD": (DOCS / "HLD.md", "Sentinel — High Level Design"),
    "PRESENTATION": (DOCS / "PRESENTATION.md", "Sentinel — Solution Presentation"),
    "MEASUREMENTS": (DOCS / "MEASUREMENTS.md", "Sentinel — Measurements"),
    "WORKFLOW-DIAGRAM": (DOCS / "WORKFLOW_DIAGRAM.md", "Sentinel — Workflow & Integration Diagram"),
}

# Print stylesheet. Serif for body because these are read as documents, mono for
# the code and the many measurement tables, and page breaks before each H2 in
# the presentation so one slide does not straddle two pages.
CSS = """
@page { size: A4; margin: 18mm 16mm; }
body {
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 10.5pt; line-height: 1.5; color: #14181f;
  max-width: none;
}
h1, h2, h3, h4 {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: #0b1f3a; line-height: 1.25; margin: 1.1em 0 0.45em;
}
h1 { font-size: 20pt; border-bottom: 2px solid #0b1f3a; padding-bottom: 6px; }
h2 { font-size: 14.5pt; border-bottom: 1px solid #c9d3e0; padding-bottom: 4px; }
h3 { font-size: 12pt; }
h4 { font-size: 10.5pt; letter-spacing: 0.02em; }
p { margin: 0.55em 0; }
code {
  font-family: "Consolas", "SF Mono", monospace;
  font-size: 9pt; background: #eef2f7; padding: 1px 4px; border-radius: 3px;
}
pre {
  background: #f5f7fa; border: 1px solid #dbe3ed; border-left: 3px solid #2f6ee0;
  border-radius: 4px; padding: 9px 11px; overflow-x: auto;
  page-break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8.5pt; line-height: 1.42; }
table {
  border-collapse: collapse; width: 100%; margin: 0.8em 0;
  font-size: 9pt; page-break-inside: avoid;
}
th, td { border: 1px solid #cbd5e1; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #eef2f7; font-weight: 650; }
tr:nth-child(even) td { background: #fafbfd; }
blockquote {
  margin: 0.7em 0; padding: 6px 14px;
  border-left: 3px solid #94a3b8; background: #f7f9fc; color: #33415c;
}
hr { border: none; border-top: 1px solid #d6dee8; margin: 1.4em 0; }
a { color: #1d4ed8; text-decoration: none; }
img { max-width: 100%; }
ul, ol { margin: 0.5em 0; padding-left: 1.5em; }
li { margin: 0.22em 0; }
.doc-footer {
  margin-top: 2em; padding-top: 8px; border-top: 1px solid #d6dee8;
  font-size: 8.5pt; color: #64748b;
}
"""

SLIDE_CSS = "h2 { page-break-before: always; }\nh1 + h2 { page-break-before: avoid; }"


def to_html(md_path: Path, title: str, slide_breaks: bool) -> str:
    text = md_path.read_text(encoding="utf-8")

    # Mermaid fences would render as a wall of unreadable source in a PDF, and
    # the diagrams they describe are restated in prose in both documents.
    text = re.sub(r"```mermaid.*?```", "_[diagram — see the repository]_",
                  text, flags=re.S)

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
    )
    css = CSS + (SLIDE_CSS if slide_breaks else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head>
<body>{body}
<div class="doc-footer">{title} · generated from {md_path.name} ·
Gujarat CCTV Integration Hackathon 2026</div>
</body></html>"""


def render(html_path: Path, pdf_path: Path) -> None:
    """
    Print the HTML with Chrome/Edge, trying Node/Playwright first, then falling back to browser CLI.
    """
    frontend = ROOT / "frontend"
    script = frontend / "_print_pdf.mjs"
    driver = f"""
    import {{ chromium }} from 'playwright-core'
    const browser = await chromium.launch({{ channel: 'chrome' }})
    const page = await browser.newPage()
    await page.goto({html_path.as_uri()!r}.replace(/^'|'$/g, ''), {{ waitUntil: 'networkidle' }})
    await page.pdf({{
      path: {str(pdf_path)!r}.replace(/^'|'$/g, ''),
      format: 'A4', printBackground: true,
      margin: {{ top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' }},
      displayHeaderFooter: true,
      headerTemplate: '<div></div>',
      footerTemplate: '<div style="width:100%;font-size:8pt;color:#94a3b8;padding:0 16mm;font-family:Segoe UI,Arial,sans-serif"><span style="float:right"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
    }})
    await browser.close()
    """
    script.write_text(driver, encoding="utf-8")
    try:
        result = subprocess.run(["node", str(script)], cwd=str(frontend),
                                capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return
    except Exception:
        pass
    finally:
        script.unlink(missing_ok=True)

    # Fallback to direct Edge / Chrome CLI print-to-pdf
    edge_exe = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    chrome_exe = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    exe = edge_exe if edge_exe.exists() else (chrome_exe if chrome_exe.exists() else None)
    if exe and exe.exists():
        cmd = [
            str(exe),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and pdf_path.exists():
            return

    raise RuntimeError("Failed to render PDF using Node or Browser CLI")



def main() -> int:
    parser = argparse.ArgumentParser(description="Render submission documents to PDF")
    parser.add_argument("--only", choices=sorted(TARGETS), action="append",
                        help="Render just this document; repeatable")
    args = parser.parse_args()

    names = args.only or ["HLD", "PRESENTATION", "WORKFLOW-DIAGRAM"]
    OUT.mkdir(parents=True, exist_ok=True)

    for name in names:
        md_path, title = TARGETS[name]
        if not md_path.exists():
            print(f"{name}: {md_path} not found", file=sys.stderr)
            return 1

        html = to_html(md_path, title, slide_breaks=(name == "PRESENTATION"))
        html_path = OUT / f"Sentinel-{name}.html"
        html_path.write_text(html, encoding="utf-8")

        pdf_path = OUT / f"Sentinel-{name}.pdf"
        render(html_path, pdf_path)
        html_path.unlink(missing_ok=True)

        size = pdf_path.stat().st_size / 1024
        print(f"{name:14} -> {pdf_path.relative_to(ROOT)}  ({size:.0f} KB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
