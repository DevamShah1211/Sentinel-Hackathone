"""
Render the submission documents to PDF.

    python tools/export_docs_pdf.py                    # HLD + PRESENTATION + WORKFLOW-DIAGRAM
    python tools/export_docs_pdf.py --only HLD

Converts markdown source documents to styled HTML and renders PDFs via headless Edge/Chrome.
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
    "HLD": (DOCS / "HLD.md", "Sentinel: High Level Design"),
    "PRESENTATION": (DOCS / "PRESENTATION.md", "Sentinel: Solution Presentation"),
    "MEASUREMENTS": (DOCS / "MEASUREMENTS.md", "Sentinel: Measurements"),
    "WORKFLOW-DIAGRAM": (DOCS / "WORKFLOW_DIAGRAM.md", "Sentinel: Workflow & Integration Diagram"),
}

CSS = """
@page { size: A4; margin: 15mm 14mm; }
html, body {
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 10pt; line-height: 1.45; color: #14181f;
  margin: 0; padding: 0;
}
h1, h2, h3, h4 {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: #0b1f3a; line-height: 1.2; margin: 0.9em 0 0.35em;
  page-break-after: avoid !important;
  break-after: avoid !important;
}
h1 { font-size: 18pt; border-bottom: 2px solid #0b1f3a; padding-bottom: 4px; margin-top: 0.2em; }
h2 { font-size: 13.5pt; border-bottom: 1px solid #c9d3e0; padding-bottom: 3px; }
h3 { font-size: 11.5pt; }
h4 { font-size: 10pt; letter-spacing: 0.01em; }
p, li { margin: 0.4em 0; orphans: 2; widows: 2; }
code {
  font-family: "Consolas", "SF Mono", monospace;
  font-size: 8.5pt; background: #eef2f7; padding: 1px 4px; border-radius: 3px;
}
pre {
  background: #f5f7fa; border: 1px solid #dbe3ed; border-left: 3px solid #2f6ee0;
  border-radius: 4px; padding: 6px 8px; margin: 0.5em 0;
  overflow-x: auto; font-size: 7.5pt; line-height: 1.25;
  page-break-inside: auto; break-inside: auto;
}
pre code { background: none; padding: 0; font-size: 7.5pt; line-height: 1.25; }
table {
  border-collapse: collapse; width: 100%; margin: 0.6em 0;
  font-size: 8.5pt; page-break-inside: auto; break-inside: auto;
}
tr { page-break-inside: avoid !important; break-inside: avoid !important; }
th, td { border: 1px solid #cbd5e1; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #eef2f7; font-weight: 650; }
tr:nth-child(even) td { background: #fafbfd; }
blockquote {
  margin: 0.5em 0; padding: 5px 12px;
  border-left: 3px solid #2f6ee0; background: #f7f9fc; color: #1e293b;
  page-break-inside: avoid; break-inside: avoid;
}
hr { border: none; border-top: 1px solid #d6dee8; margin: 1em 0; }
a { color: #1d4ed8; text-decoration: none; }
img { max-width: 100%; width: 100%; height: auto; max-height: 180mm; object-fit: contain; display: block; margin: 0.6em 0; page-break-inside: avoid; }
ul, ol { margin: 0.4em 0; padding-left: 1.4em; }
li { margin: 0.18em 0; }
"""

SLIDE_CSS = """
@page {
  size: A4 portrait;
  margin: 12mm 14mm 10mm 14mm;
}
html, body {
  font-size: 9.5pt;
  line-height: 1.38;
}
h1 {
  font-size: 19pt;
  margin-top: 0;
  padding-bottom: 2px;
}
h2 {
  font-size: 13.5pt;
  margin-top: 0;
  color: #0b1f3a;
  border-bottom: 2px solid #2f6ee0;
  padding-bottom: 3px;
  page-break-before: always !important;
  break-before: page !important;
}
h3 {
  font-size: 11pt;
  margin: 0.4em 0 0.2em;
  page-break-after: avoid !important;
  break-after: avoid !important;
}
hr {
  display: none;
}
img {
  max-width: 100%;
  width: auto;
  height: auto;
  max-height: 94mm;
  object-fit: contain;
  display: block;
  margin: 0.35em auto;
  page-break-inside: avoid !important;
  break-inside: avoid !important;
}
table {
  page-break-inside: avoid !important;
  break-inside: avoid !important;
  margin: 0.35em 0;
  font-size: 8pt;
}
blockquote {
  margin: 0.35em 0;
  padding: 4px 10px;
  page-break-inside: avoid !important;
  break-inside: avoid !important;
  font-size: 8.5pt;
}
p, li {
  margin: 0.25em 0;
}
ul, ol {
  margin: 0.25em 0;
  padding-left: 1.3em;
}
"""


def to_html(md_path: Path, title: str, slide_breaks: bool) -> str:
    text = md_path.read_text(encoding="utf-8")

    # Clean any stray em-dashes
    text = text.replace(" — ", " : ").replace("—", "-")

    text = re.sub(r"```mermaid.*?```", "_[diagram: see the repository]_",
                  text, flags=re.S)

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
    )

    # Inline images as base64 so they render in headless browser (file:// has no relative resolution)
    import base64, mimetypes as _mt
    def _inline_img(m: "re.Match[str]") -> str:
        tag, src = m.group(1), m.group(2)
        # Try resolving relative to the markdown file's directory first, then ROOT
        for base in (md_path.parent, ROOT):
            candidate = (base / src).resolve()
            if candidate.exists():
                mime, _ = _mt.guess_type(str(candidate))
                mime = mime or "image/png"
                data = base64.b64encode(candidate.read_bytes()).decode()
                return f'{tag}src="data:{mime};base64,{data}"'
        return m.group(0)  # leave unchanged if not found

    # markdown renders: <img alt="..." src="PATH"> — src can be anywhere in the tag
    body = re.sub(r'(<img\s[^>]*?)src="([^"]+)"', _inline_img, body)

    css = CSS + (SLIDE_CSS if slide_breaks else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head>
<body>{body}
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
      margin: {{ top: '15mm', bottom: '15mm', left: '14mm', right: '14mm' }},
      displayHeaderFooter: true,
      headerTemplate: '<div></div>',
      footerTemplate: '<div style="width:100%;font-size:8pt;color:#94a3b8;padding:0 14mm;font-family:Segoe UI,Arial,sans-serif"><span style="float:right"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
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
