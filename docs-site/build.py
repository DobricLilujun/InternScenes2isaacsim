#!/usr/bin/env python3
"""SAGE-Bench docs build.

A dependency-free (stdlib-only) static-site builder.  It reads the markdown
sources under ``source/`` and emits a self-contained HTML site (with a
custom robotic/CV theme, a custom logo and a client-side full-text search
powered by Lunr.js) into ``output/``.

The output is ready to be served by GitHub Pages at
``https://dobriclilujun.github.io/SAGE-Bench``.

Run:
    python3 build.py            # build into docs-site/output/
    python3 build.py --clean    # wipe output/ first
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "source"
ASSETS = ROOT / "assets"
OUT = ROOT / "output"

# ---------------------------------------------------------------------------
# navigation + page metadata (the "open-source doc split")
# ---------------------------------------------------------------------------
# Each entry: (slug, title, group)
NAV = [
    ("index", "Overview", "SAGE-Bench"),
    ("installation", "Installation", "Getting Started"),
    ("quickstart", "Quickstart", "Getting Started"),
    ("scene_graph_schema", "Scene-Graph Schema", "Core"),
    ("relations", "Relations & Edge Families", "Core"),
    ("reference_frames", "Reference Frames", "Core"),
    ("vlm_annotation", "VLM Annotation", "Annotation"),
    ("evaluation", "Evaluation Metrics", "Evaluation"),
    ("benchmark", "Benchmark", "Evaluation"),
    ("rendering", "Multi-View Rendering", "Pipeline"),
    ("python_api", "Python API", "Reference"),
    ("cli", "CLI Reference", "Reference"),
    ("contributing", "Contributing", "Community"),
]

# group order for the sidebar
GROUPS = ["SAGE-Bench", "Getting Started", "Core", "Annotation",
         "Evaluation", "Pipeline", "Reference", "Community"]

SITE = {
    "title": "SAGE-Bench",
    "tagline": "Scene-graph Assessment & Generation Evaluation",
    "version": "1.0",
    "repo": "https://github.com/DobricLilujun/SAGE-Bench",
    "pages": "https://dobriclilujun.github.io/SAGE-Bench",
}


def _group_of(slug: str) -> str:
    for s, _t, g in NAV:
        if s == slug:
            return g
    return ""


# ---------------------------------------------------------------------------
# minimal, robust Markdown -> HTML converter
# ---------------------------------------------------------------------------
def _code_highlight(code: str, lang: str) -> str:
    """Very small, dependency-free syntax colouriser (Python/JSON/shell)."""
    escaped = html.escape(code, quote=False)
    if lang in ("py", "python"):
        escaped = re.sub(r"(#[^\n]*)", r'<span class="c-com">\1</span>', escaped)
        escaped = re.sub(r"(\bdef\b|\bclass\b|\breturn\b|\bimport\b|\bfrom\b"
                         r"|\bwith\b|\bas\b|\bfor\b|\bin\b|\bif\b|\belse\b"
                         r"|\btry\b|\bexcept\b|\braise\b|\bpass\b|\bTrue\b"
                         r"|\bFalse\b|\bNone\b|\blambda\b|\byield\b|\bassert\b)",
                         r'<span class="c-kw">\1</span>', escaped)
        escaped = re.sub(r"(\b\d+\.?\d*\b)", r'<span class="c-num">\1</span>', escaped)
        escaped = re.sub(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.*)\')',
                         r'<span class="c-str">\1</span>', escaped)
    elif lang in ("json",):
        escaped = re.sub(r'("(?:[^"\\]|\\.)*")(\s*:)',
                         r'<span class="c-str">\1</span>\2', escaped)
        escaped = re.sub(r':(\\s*)("(?:[^"\\]|\\.)*")',
                         r':\\1<span class="c-str">\\2</span>', escaped)
        escaped = re.sub(r'(\b-?\d+\.?\d*\b)', r'<span class="c-num">\1</span>', escaped)
        escaped = re.sub(r'(\btrue\b|\bfalse\b|\bnull\b)',
                         r'<span class="c-kw">\1</span>', escaped)
    elif lang in ("sh", "bash", "console"):
        escaped = re.sub(r"(#[^\n]*)", r'<span class="c-com">\1</span>', escaped)
        escaped = re.sub(r'(\binternscenes\b|\bpython\b|\buv\b|\bexport\b)',
                         r'<span class="c-kw">\1</span>', escaped)
    else:
        escaped = re.sub(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.*)\')',
                         r'<span class="c-str">\1</span>', escaped)
    return escaped


def _inline(text: str) -> str:
    """Inline markdown: code, bold, italic, links, images, autolinks."""
    out = []
    # protect code spans first
    parts = re.split(r"(`.+?`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            body = part[1:-1]
            out.append(f'<code class="inl">{html.escape(body)}</code>')
        else:
            t = part
            # images
            t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                       r'<img alt="\1" src="\2" />', t)
            # links
            t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                       r'<a href="\2">\1</a>', t)
            # bold
            t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
            # italic
            t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
            out.append(t)
    return "".join(out)


def _convert(md: str) -> str:
    """Block-level Markdown -> HTML."""
    md = md.replace("\r\n", "\n")
    lines = md.split("\n")
    html_blocks: list[str] = []
    i = 0
    n = len(lines)

    def flush_list(items: list[tuple[int, str]], ordered: bool) -> None:
        tag = "ol" if ordered else "ul"
        html_blocks.append(f"<{tag}>")
        for level, text in items:
            if level == 0:
                html_blocks.append(f'<li>{_inline(text)}</li>')
        html_blocks.append(f"</{tag}>")

    i = 0
    while i < n:
        line = lines[i]

        # fenced code block
        m = re.match(r"^```(\w*)\s*$", line.strip())
        if m:
            lang = m.group(1) or "text"
            body: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code = "\n".join(body)
            html_blocks.append(
                f'<pre class="code"><code class="lang-{lang}">'
                f'{_code_highlight(code, lang)}</code></pre>'
            )
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            level = len(m.group(1))
            title = _inline(m.group(2))
            html_blocks.append(f"<h{level}>{title}</h{level}>")
            i += 1
            continue

        # horizontal rule
        if re.match(r"^---+\s*$", line.strip()):
            html_blocks.append("<hr />")
            i += 1
            continue

        # blockquote
        if line.strip().startswith(">"):
            quote: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            html_blocks.append(
                f'<blockquote>{" ".join(quote)}</blockquote>'
            )
            continue

        # table
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?\s*[:\-| ]+\|?\s*$",
                                                  lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|")
                            .split("|")])
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in header)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            html_blocks.append(
                f'<div class="table-wrap"><table><thead><tr>{th}</tr>'
                f'</thead><tbody>{body}</tbody></table></div>'
            )
            continue

        # lists (handles indented continuation lines + one level of nesting)
        if re.match(r"^\s*[-*+]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            items: list[tuple[int, str]] = []
            while i < n:
                lm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not lm:
                    break
                depth = len(lm.group(1)) // 2
                text = lm.group(3)
                i += 1
                # consume indented continuation lines (part of this item)
                while i < n and lines[i].strip() and \
                        len(re.match(r"^\s*", lines[i]).group(0)) >= max(2, len(lm.group(1))):
                    if re.match(r"^\s*[-*+]\s+", lines[i]) or \
                       re.match(r"^\s*\d+\.\s+", lines[i]):
                        break
                    text += " " + lines[i].strip()
                    i += 1
                items.append((depth, text))
            _tag = "ol" if ordered else "ul"
            out = ["<" + _tag + ">"]
            in_sub = False
            for depth, text in items:
                if depth == 0:
                    if in_sub:
                        out.append("</ul>")
                        in_sub = False
                    out.append(f"<li>{_inline(text)}</li>")
                else:
                    if not in_sub:
                        out.append('<ul>')
                        in_sub = True
                    out.append(f'<li>{_inline(text)}</li>')
            if in_sub:
                out.append("</ul>")
            out.append("</" + _tag + ">")
            html_blocks.append("".join(out))
            continue

        # raw HTML block (e.g. <div class="hero"> ... </div>)
        if re.match(r"^\s*<\s*(/?)\s*[a-zA-Z][^>]*>", line) or \
           (line.strip().startswith("<") and re.search(r"<[a-zA-Z/][^>]*>", line)):
            block: list[str] = []
            while i < n and (lines[i].strip() or _html_open(lines[i])):
                # stop at a blank line (HTML block is finished) unless the
                # open tag count still exceeds the close tag count
                block.append(lines[i])
                i += 1
                if _balanced(block):
                    break
            html_blocks.append("\n".join(block).strip())
            continue

        # blank line
        if not line.strip():
            i += 1
            continue

        # paragraph
        para: list[str] = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        if para:
            html_blocks.append(f"<p>{_inline(' '.join(para))}</p>")

    return "\n".join(html_blocks)


def _html_open(line: str) -> bool:
    o = len(re.findall(r"<[a-zA-Z][^>]*>", line))
    c = len(re.findall(r"</[a-zA-Z][^>]*>", line))
    return o > c


def _balanced(block: list[str]) -> bool:
    # balanced when, up to this block, all opened tags have been closed
    text = "\n".join(block)
    o = len(re.findall(r"<[a-zA-Z][^>]*>", text))
    c = len(re.findall(r"</[a-zA-Z][^>]*>", text))
    return c >= o and o > 0


def _is_block_start(line: str) -> bool:
    return bool(
        re.match(r"^(#{1,6})\s+", line)
        or line.strip().startswith("```")
        or re.match(r"^\s*[-*+]\s+", line)
        or re.match(r"^\s*\d+\.\s+", line)
        or line.strip().startswith(">")
        or re.match(r"^---+\s*$", line.strip())
        or re.match(r"^\s*<\s*(/?)\s*[a-zA-Z]", line)
    )


# ---------------------------------------------------------------------------
# front matter
# ---------------------------------------------------------------------------
def _parse_front_matter(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"')
        body = text[m.end():]
    return meta, body


# ---------------------------------------------------------------------------
# search index
# ---------------------------------------------------------------------------
def _build_search_index() -> list[dict]:
    index: list[dict] = []
    for slug, title, _g in NAV:
        p = SRC / f"{slug}.md"
        if not p.exists():
            continue
        meta, body = _parse_front_matter(p.read_text(encoding="utf-8"))
        # strip markdown syntax for a clean searchable text
        clean = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
        clean = re.sub(r"[#>*|`_]", " ", clean)
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        index.append({
            "slug": slug,
            "title": meta.get("title", title),
            "text": clean[:4000],
        })
    return index


# ---------------------------------------------------------------------------
# theme / page shell
# ---------------------------------------------------------------------------
def _sidebar(active: str) -> str:
    items = []
    for group in GROUPS:
        pages = [(s, t) for s, t, g in NAV if g == group]
        if not pages:
            continue
        links = []
        for s, t in pages:
            cls = " active" if s == active else ""
            links.append(
                f'<a class="nav-link{cls}" href="{s}.html">{html.escape(t)}</a>'
            )
        items.append(
            f'<div class="nav-group"><div class="nav-title">{group}</div>'
            f'<div class="nav-links">{"".join(links)}</div></div>'
        )
    return "".join(items)


def _relativize(page: str) -> str:
    # GitHub Pages *project* pages live at /<repo>/, so absolute paths like
    # href="/foo.html" would resolve to the domain root and break. Rewrite any
    # absolute href/src (but NOT http/https external links) to a relative path.
    def _strip(m: "re.Match") -> str:
        attr, _, val = m.group(1), m.group(2), m.group(3)
        return f'{attr}="{val[1:]}"' if val.startswith("/") else m.group(0)

    return re.sub(r'(href|src)(\s*=\s*")(/[^"\s]*)"', _strip, page)


def _shell(active: str, title: str, description: str, content: str) -> str:
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="description" content="{html.escape(description)}" />
<title>{html.escape(title)} · {SITE["title"]}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" />
<link rel="icon" type="image/svg+xml" href="assets/logo.svg" />
<link rel="stylesheet" href="assets/style.css" />
<script src="https://cdn.jsdelivr.net/npm/lunr@2.3.9/lunr.min.js" defer></script>
<script src="assets/search.js" defer></script>
</head>
<body>
<div class="scanline"></div>
<header class="topbar">
  <a class="brand" href="index.html">
    <img src="assets/logo.svg" alt="{SITE["title"]} logo" class="brand-logo" />
    <span class="brand-name">{SITE["title"]}</span>
    <span class="brand-tag">{html.escape(SITE["tagline"])}</span>
  </a>
  <div class="search">
    <span class="search-ico">⌕</span>
    <input id="search-input" type="search" placeholder="Search the docs…  ( / )"
           autocomplete="off" aria-label="Search" />
    <div id="search-results" class="search-results" hidden></div>
  </div>
  <div class="topbar-right">
    <a href="{SITE["repo"]}" class="gh-link" title="GitHub">GH</a>
    <span class="ver">v{html.escape(SITE["version"])}</span>
  </div>
  <button class="menu-toggle" aria-label="Menu">☰</button>
</header>
<div class="layout">
  <aside class="sidebar">
    <nav class="nav">{_sidebar(active)}</nav>
    <div class="nav-foot">
      <div class="chip">MIT</div>
      <div class="chip">Open Source</div>
    </div>
  </aside>
  <main class="content">
    <article class="doc">
      {content}
    </article>
    <footer class="foot">
      <div>Built with <span class="mono">build.py</span> · {SITE["title"]}
        v{html.escape(SITE["version"])}</div>
      <div class="foot-links">
        <a href="{SITE["repo"]}">GitHub</a>
        <a href="contributing.html">Contribute</a>
      </div>
    </footer>
  </main>
</div>
</body>
</html>
"""
    return _relativize(page)


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)

    index = _build_search_index()

    for slug, title, _g in NAV:
        p = SRC / f"{slug}.md"
        if not p.exists():
            print(f"  ! missing source for {slug}")
            continue
        meta, body = _parse_front_matter(p.read_text(encoding="utf-8"))
        title = meta.get("title", title)
        description = meta.get("description",
                              f"{title} — {SITE['tagline']}")
        content_html = _convert(body)
        page = _shell(slug, title, description, content_html)
        (OUT / f"{slug}.html").write_text(page, encoding="utf-8")

    # copy static assets
    for name in ("style.css", "search.js", "logo.svg", "logo-mark.svg"):
        src = ASSETS / name
        if src.exists():
            shutil.copy2(src, OUT / "assets" / name)

    # search index
    (OUT / "assets" / "search-index.json").write_text(
        json.dumps({"pages": index}), encoding="utf-8")

    # a redirect for the bare domain root is already index.html
    n = len(list(OUT.glob("*.html")))
    print(f"built {n} pages + {len(index)} search entries -> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    build()
