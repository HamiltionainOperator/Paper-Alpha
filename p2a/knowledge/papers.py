"""Ingest research papers: local PDF/TXT/MD/HTML files, folders, URLs and arXiv ids."""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from ..store import Store
from ..util import chunk_text, console, esc, html_to_text, stable_hash

ARXIV_ID = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)$", re.I)
UA = {"User-Agent": "paper2alpha/0.1 (research paper ingestion)"}


def pdf_to_text(data: bytes | str | Path) -> tuple[str, str]:
    """Return (title, text) from a PDF using pdfplumber, falling back to pypdf."""
    src = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else str(data)
    try:
        import pdfplumber
        with pdfplumber.open(src) as pdf:
            title = (pdf.metadata or {}).get("Title") or ""
            pages = [p.extract_text() or "" for p in pdf.pages]
        return title, "\n\n".join(pages)
    except ImportError:
        pass
    from pypdf import PdfReader  # optional fallback
    reader = PdfReader(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else str(data))
    title = (reader.metadata or {}).get("/Title") or ""
    return title, "\n\n".join(p.extract_text() or "" for p in reader.pages)


def clean_text(text: str) -> str:
    t = text.replace("\r", "")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)                 # de-hyphenate line breaks
    t = re.sub(r"[ \t]*\n[ \t]*(?=[a-z(,;])", " ", t)       # join wrapped lines
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    lines = t.split("\n")
    for i in range(len(lines) - 1, int(len(lines) * 0.5), -1):  # drop trailing reference list
        if re.fullmatch(r"\s*(\d+\.?\s*)?(references|bibliography|works cited)\s*", lines[i], re.I):
            t = "\n".join(lines[:i])
            break
    return t.strip()


def _first_line_title(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if 12 <= len(s) <= 200 and not s.lower().startswith(("arxiv", "http", "doi")):
            return s
    return "Untitled paper"


def fetch_arxiv(arxiv_id: str) -> tuple[str, str, dict]:
    meta_xml = requests.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id}, headers=UA, timeout=60)
    meta_xml.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = ET.fromstring(meta_xml.text).find("a:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv id not found: {arxiv_id}")
    title = re.sub(r"\s+", " ", entry.findtext("a:title", "", ns)).strip()
    abstract = re.sub(r"\s+", " ", entry.findtext("a:summary", "", ns)).strip()
    authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]
    body = ""
    try:
        pdf = requests.get(f"https://arxiv.org/pdf/{arxiv_id}", headers=UA, timeout=120)
        if pdf.ok and pdf.content[:4] == b"%PDF":
            body = pdf_to_text(pdf.content)[1]
    except requests.RequestException:
        pass
    text = f"{title}\n\nAbstract\n{abstract}\n\n{body}" if body else f"{title}\n\nAbstract\n{abstract}"
    return title, text, {"arxiv_id": arxiv_id, "authors": authors, "abstract": abstract}


def fetch_url(url: str) -> tuple[str, str, dict]:
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "pdf" in ctype or r.content[:4] == b"%PDF":
        title, text = pdf_to_text(r.content)
        return title or _first_line_title(text), text, {"url": url}
    html = r.text
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    text = html_to_text(html)
    return (re.sub(r"\s+", " ", m.group(1)).strip() if m else _first_line_title(text)), text, {"url": url}


def load_source(src: str) -> tuple[str, str, dict]:
    m = ARXIV_ID.match(src.strip())
    if m:
        return fetch_arxiv(m.group(1))
    am = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$", src)
    if am:
        return fetch_arxiv(am.group(1))
    if src.startswith(("http://", "https://")):
        return fetch_url(src)
    p = Path(src).expanduser()
    if not p.is_file():
        raise FileNotFoundError(src)
    if p.suffix.lower() == ".pdf":
        title, text = pdf_to_text(p)
        return title or _first_line_title(text) or p.stem, text, {"file": str(p)}
    raw = p.read_text(errors="replace")
    if p.suffix.lower() in (".html", ".htm"):
        raw = html_to_text(raw)
    return _first_line_title(raw) or p.stem, raw, {"file": str(p)}


def expand_sources(sources: list[str]) -> list[str]:
    out = []
    for s in sources:
        p = Path(s).expanduser()
        if p.is_dir():
            out += sorted(str(f) for f in p.rglob("*") if f.suffix.lower() in (".pdf", ".txt", ".md", ".html", ".htm"))
        else:
            out.append(s)
    return out


def ingest(sources: list[str], store: Store) -> list[str]:
    ids = []
    for src in expand_sources(sources):
        try:
            title, text, meta = load_source(src)
        except Exception as e:  # keep going on bad inputs
            console.print(f"[red]  could not read {esc(src)}: {esc(str(e))}[/red]")
            continue
        text = clean_text(text)
        if len(text) < 300:
            console.print(f"[yellow]  {src}: very little text extracted ({len(text)} chars) - scanned PDF?[/yellow]")
        doc_id = "paper:" + stable_hash([title, len(text), text[:2000]])[:12]
        store.add_document(doc_id, "paper", title, src, text, chunk_text(text), meta={**meta, "chars": len(text)})
        console.print(f"  ingested [bold]{esc(title[:90])}[/bold] ({len(text):,} chars) -> {doc_id}")
        ids.append(doc_id)
    return ids
