"""Small shared helpers."""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser

try:
    from rich.console import Console
    from rich.markup import escape as esc
    console = Console(emoji=False)  # model ids like "x:free:" must not become emoji
except ImportError:  # pragma: no cover - rich is optional
    def esc(text):
        return text

    class _Plain:
        def print(self, *a, **k):
            print(*a)

        def rule(self, title=""):
            print(f"---- {title} ----")
    console = _Plain()


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html or "")
    text = "".join(p.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    """Split on paragraph boundaries into ~size-char chunks with some overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for para in paras:
        while len(para) > size:
            head, para = para[:size], para[size - overlap:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if len(cur) + len(para) + 2 > size and cur:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + para if overlap else para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks


def truncate(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."
