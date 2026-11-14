"""Office documents as something the Files viewer can show, with the standard library only.

Word (.docx), PowerPoint (.pptx) and OpenDocument text / slides (.odt, .odp) become Markdown (headings, lists,
tables, bold / italic, links, pictures); spreadsheets (.xlsx, .ods) become the rows of each sheet, as displayed.
The page layout is not kept: this is the content, readable on any screen. The old binary formats (.doc, .xls,
.ppt) are not read.

These files are zip archives of XML written by anyone: nothing in them is executed or fetched, every part is
read up to a size, the whole reading has a deadline and the answer a size (`truncated` says it was cut). A DTD
is refused (these formats have none), and expat (>= 2.4.1) bounds entity expansion by itself.
"""
from __future__ import annotations

import math
import posixpath
import re
import time
import zipfile
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

KINDS = {".docx": "text", ".docm": "text", ".odt": "text",
         ".xlsx": "sheets", ".xlsm": "sheets", ".ods": "sheets",
         ".pptx": "slides", ".pptm": "slides", ".ppsx": "slides", ".odp": "slides"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".bmp": "image/bmp"}

PART_MAX = 16 << 20        # an XML part read whole (decompressed)
STREAM_MAX = 256 << 20     # a sheet or the shared strings, read as a stream and left as soon as enough is known
TEXT_MAX = 1_500_000       # characters of Markdown
ROWS_MAX = 5000            # per sheet
COLS_MAX = 200
CELLS_MAX = 300_000        # filled cells, all sheets together
CELL_MAX = 2000            # characters of one cell
STRINGS_MAX = 1_000_000    # shared strings of a workbook
SHEETS_MAX = 40
SLIDES_MAX = 500
MEDIA_MAX = 24 << 20       # one picture of a document
TIME_S = 8.0


class Unreadable(Exception):
    """`code`: `unsupported` (not a document we read, damaged, protected by a password) or `too_large`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Full(Exception):
    """Out of time or of room: what was read so far is the answer, marked truncated."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strip(root: ET.Element) -> ET.Element:
    """Local names only (the strict and transitional flavours of OOXML differ by their namespaces alone); the
    attributes of the relationships namespace keep an `r:` (`<p:sldId id= r:id=>`)."""
    for el in root.iter():
        if el.tag[0] == "{":
            el.tag = el.tag.rsplit("}", 1)[1]
        if el.attrib:
            attrs = {}
            for k, v in el.attrib.items():
                if k[0] == "{":
                    ns, k = k[1:].rsplit("}", 1)
                    if ns.endswith("/relationships"):
                        k = "r:" + k
                attrs[k] = v
            el.attrib.clear()
            el.attrib.update(attrs)
    return root


def _no_dtd(data: bytes) -> None:
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise Unreadable("unsupported", "This document cannot be read")


class _Capped:
    """A part read as a stream: stops (truncated) past STREAM_MAX bytes or the deadline."""

    def __init__(self, f, pack: "_Pack"):
        self.f, self.pack, self.n = f, pack, 0

    def read(self, size: int = -1) -> bytes:
        self.pack.tick()
        if self.n > STREAM_MAX:
            raise _Full
        data = self.f.read(size if size and size > 0 else 1 << 16)
        if not self.n:
            _no_dtd(data)
        self.n += len(data)
        return data


_ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, OSError, EOFError, RuntimeError, NotImplementedError, ValueError)


class _Pack:
    """The archive of a document: its parts, their relationships, and the budget of the reading."""

    def __init__(self, path: Path):
        try:
            self.zf = zipfile.ZipFile(path)
        except _ZIP_ERRORS:
            raise Unreadable("unsupported", "This document cannot be read (damaged, or protected by a password)") from None
        self.names = {i.filename: i for i in self.zf.infolist()[:20000]}
        self.deadline = time.monotonic() + TIME_S
        self.left = TEXT_MAX
        self.cells = CELLS_MAX
        self.truncated = False

    def close(self) -> None:
        self.zf.close()

    def tick(self) -> None:
        if time.monotonic() > self.deadline:
            raise _Full

    def data(self, name: str, cap: int | None = None) -> bytes | None:
        info = self.names.get(name)
        if info is None:
            return None
        cap = PART_MAX if cap is None else cap
        if info.file_size > cap:
            raise Unreadable("too_large", "This document is too large to be shown")
        try:
            with self.zf.open(info) as f:
                data = f.read(cap + 1)
        except _ZIP_ERRORS:
            raise Unreadable("unsupported", "This document cannot be read") from None
        if len(data) > cap:
            raise Unreadable("too_large", "This document is too large to be shown")
        return data

    def xml(self, name: str) -> ET.Element | None:
        data = self.data(name)
        if data is None:
            return None
        _no_dtd(data)
        try:
            return _strip(ET.fromstring(data))
        except ET.ParseError:
            raise Unreadable("unsupported", "This document cannot be read") from None

    def stream(self, name: str):
        """(event, element) of a large part, `start` and `end`; nothing when the part is missing."""
        info = self.names.get(name)
        if info is None:
            return
        try:
            with self.zf.open(info) as f:
                yield from ET.iterparse(_Capped(f, self), events=("start", "end"))
        except ET.ParseError:
            raise _Full from None
        except _ZIP_ERRORS:
            raise Unreadable("unsupported", "This document cannot be read") from None

    def rels(self, part: str) -> dict[str, tuple[str, bool, str]]:
        """Relationship id -> (target: a part of the archive or an outside URL, outside, type)."""
        folder, base = posixpath.split(part)
        root = self.xml(posixpath.join(folder, "_rels", base + ".rels"))
        out: dict[str, tuple[str, bool, str]] = {}
        for r in root if root is not None else ():
            target, outside = r.get("Target", ""), r.get("TargetMode") == "External"
            if not outside:
                target = target[1:] if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            out[r.get("Id", "")] = (target, outside, r.get("Type", ""))
        return out

    def main(self, default: str) -> str:
        """The main part of an OOXML package (named by the root relationships, else its usual place)."""
        for target, outside, kind in self.rels("").values():
            if kind.endswith("/officeDocument") and not outside and target in self.names:
                return target
        return default

    def typed(self, rels: dict[str, tuple[str, bool, str]], kind: str, default: str = "") -> str:
        return next((t for t, outside, k in rels.values() if k.endswith("/" + kind) and not outside), default)

    def image(self, target: str) -> str:
        """The Markdown of a picture of the archive ('' when it is not one a browser shows)."""
        if posixpath.splitext(target)[1].lower() not in IMAGE_TYPES or target not in self.names:
            return ""
        return f"![]({quote(target)})"


# ---- Markdown ------------------------------------------------------------------------------
_ESC = re.compile(r"([\\`*_\[\]<>&#|~])")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_LEAD = re.compile(r"^(\s*)(?:(\d+)([.)])(?=\s|$)|([-+=]))", re.M)
_SPACE = re.compile(r"[ \t\r\f\v ]+")


def _esc(s: str) -> str:
    return _ESC.sub(r"\\\1", _CTRL.sub("", s))


def _lead(s: str) -> str:
    """A line that starts like a list item or a heading underline stays text."""
    return _LEAD.sub(lambda m: m[1] + (f"{m[2]}\\{m[3]}" if m[2] else "\\" + m[4]), s)


def _url(url: str | None) -> str:
    """A web or mail address a document may link to, safe inside `(...)`; '' for anything else."""
    url = (url or "").strip()
    if not re.match(r"(?i)(https?://|mailto:)", url):
        return ""
    return quote(url, safe=":/?#[]@!$&'*+,;=%-._~").replace("(", "%28").replace(")", "%29")


class _Inline:
    """The text of a paragraph: runs with their bold / italic / strike / link, then one line of Markdown."""

    def __init__(self) -> None:
        self.segs: list[list] = []

    def add(self, text: str, bold: bool = False, italic: bool = False, strike: bool = False, link: str = "") -> None:
        if not text:
            return
        fmt = [bold, italic, strike, link]
        if self.segs and self.segs[-1][1:] == fmt:
            self.segs[-1][0] += text
        else:
            self.segs.append([text, *fmt])

    def raw(self, md: str) -> None:
        if md:
            self.segs.append([md, None, None, None, None])

    def md(self, plain: bool = False, cell: bool = False) -> str:
        out = []
        for text, bold, italic, strike, link in self.segs:
            if bold is None:
                out.append(text)
                continue
            text = _SPACE.sub(" ", text)
            core = text.strip()
            if not core:
                out.append("\n" if "\n" in text else " ")
                continue
            lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
            core = _esc(core)
            mark = "" if plain else ("**" if bold else "") + ("*" if italic else "")
            core = f"{mark}{core}{mark}"
            if strike and not plain:
                core = f"~~{core}~~"
            if link:
                core = f"[{core}]({link})"
            out.append(lead + core + trail)
        lines = [ln.strip() for ln in "".join(out).split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        if cell:
            return " · ".join(ln for ln in lines if ln)
        return "\\\n".join(_lead(ln) for ln in lines)


class _Out:
    """The blocks of the Markdown answer, within the text budget."""

    def __init__(self, pack: _Pack):
        self.pack = pack
        self.blocks: list[tuple[str, bool]] = []
        self.depth = -1                     # level of the list item just written (-1: not in a list)

    def _add(self, md: str, item: bool = False) -> None:
        self.pack.tick()
        self.pack.left -= len(md) + 2
        if self.pack.left < 0:
            raise _Full
        self.blocks.append((md, item))
        if not item:
            self.depth = -1

    def para(self, md: str) -> None:
        if md:
            self._add(md)

    def heading(self, level: int, md: str) -> None:
        md = md.replace("\\\n", " ")
        if md:
            self._add("#" * max(1, min(level, 6)) + " " + md)

    def item(self, level: int, ordered: bool, md: str) -> None:
        if not md:
            return
        level = max(0, min(level, self.depth + 1, 8))    # never deeper than one level under the item above
        marker = "1. " if ordered else "- "
        pad = " " * (4 * level)
        self._add(pad + marker + md.replace("\n", "\n" + pad + " " * len(marker)), True)
        self.depth = level

    def quote(self, md: str) -> None:
        if md:
            self._add("> " + md.replace("\n", "\n> "))

    def rule(self) -> None:
        self._add("---")

    def table(self, rows: list[list[str]]) -> None:
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            return
        n = min(max(len(r) for r in rows), 40)

        def line(r: list[str]) -> str:
            return "| " + " | ".join((r[i] if i < len(r) else "") or " " for i in range(n)) + " |"
        self._add("\n".join([line(rows[0]), "|" + " --- |" * n, *(line(r) for r in rows[1:])]))

    def text(self) -> str:
        out: list[str] = []
        was_item = False
        for md, item in self.blocks:
            if out:
                out.append("\n" if item and was_item else "\n\n")
            out.append(md)
            was_item = item
        return "".join(out) + ("\n" if out else "")


def _on(props: ET.Element | None, name: str) -> bool:
    el = props.find(name) if props is not None else None
    return el is not None and el.get("val", "true") not in ("0", "false", "off", "none")


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# ---- Word ----------------------------------------------------------------------------------
class _Docx:
    def __init__(self, pack: _Pack, out: _Out):
        self.pack, self.out = pack, out
        self.part = pack.main("word/document.xml")
        self.rels = pack.rels(self.part)
        self.heads: dict[str, int] = {}                  # style id -> heading level
        self.style_list: dict[str, tuple[str, int]] = {}  # style id -> (numId, level)
        self.style_level: dict[str, int] = {}             # style id -> list level its name gives ("List Bullet 2")
        self.ordered: dict[tuple[str, int], bool] = {}   # (numId, level) -> numbered
        self.boxes: list[ET.Element] = []                # text boxes met in the paragraph being read
        self._styles()
        self._numbering()

    def _styles(self) -> None:
        root = self.pack.xml(self.pack.typed(self.rels, "styles", "word/styles.xml"))
        based: dict[str, str] = {}
        for st in root.findall("style") if root is not None else ():
            sid = st.get("styleId", "")
            name = (st.find("name").get("val", "") if st.find("name") is not None else "").lower()
            ppr = st.find("pPr")
            m = re.fullmatch(r"heading (\d)", name)
            if m:
                self.heads[sid] = int(m[1])
            elif name == "title":
                self.heads[sid] = 1
            elif ppr is not None and ppr.find("outlineLvl") is not None:
                self.heads[sid] = _int(ppr.find("outlineLvl").get("val"), 8) + 1
            m = re.fullmatch(r"list (?:bullet|number) (\d)", name)
            if m:
                self.style_level[sid] = int(m[1]) - 1
            num = ppr.find("numPr") if ppr is not None else None
            if num is not None and num.find("numId") is not None:
                self.style_list[sid] = (num.find("numId").get("val", ""), _int(num.find("ilvl").get("val")) if num.find("ilvl") is not None else 0)
            if st.find("basedOn") is not None:
                based[sid] = st.find("basedOn").get("val", "")
        for sid in based:                                 # a style based on a heading is a heading
            seen, cur = 0, sid
            while cur in based and cur not in self.heads and seen < 10:
                cur, seen = based[cur], seen + 1
            if cur in self.heads and sid not in self.heads:
                self.heads[sid] = self.heads[cur]

    def _numbering(self) -> None:
        target = self.pack.typed(self.rels, "numbering", "word/numbering.xml")
        root = self.pack.xml(target)
        if root is None:
            return
        fmts: dict[tuple[str, int], str] = {}
        for ab in root.findall("abstractNum"):
            for lvl in ab.findall("lvl"):
                fmt = lvl.find("numFmt")
                fmts[(ab.get("abstractNumId", ""), _int(lvl.get("ilvl")))] = fmt.get("val", "") if fmt is not None else ""
        for num in root.findall("num"):
            ab = num.find("abstractNumId")
            if ab is None:
                continue
            for (aid, lvl), fmt in fmts.items():
                if aid == ab.get("val"):
                    self.ordered[(num.get("numId", ""), lvl)] = fmt not in ("bullet", "none", "")

    def read(self) -> None:
        root = self.pack.xml(self.part)
        body = root.find("body") if root is not None else None
        if body is None:
            raise Unreadable("unsupported", "This document cannot be read")
        self.blocks(body)

    def blocks(self, parent: ET.Element) -> None:
        for el in parent:
            self.pack.tick()                              # empty paragraphs by the million write nothing
            if el.tag == "p":
                self.para(el)
            elif el.tag == "tbl":
                self.table(el)
            elif el.tag == "sdt":
                content = el.find("sdtContent")
                if content is not None:
                    self.blocks(content)
            elif el.tag in ("ins", "customXml", "smartTag"):
                self.blocks(el)

    def para(self, el: ET.Element) -> None:
        ppr = el.find("pPr")
        style = ppr.find("pStyle").get("val", "") if ppr is not None and ppr.find("pStyle") is not None else ""
        level = self.heads.get(style)
        if level is None and re.fullmatch(r"(?i)heading\s?(\d)", style):
            level = int(style[-1])
        if ppr is not None and ppr.find("outlineLvl") is not None:
            level = _int(ppr.find("outlineLvl").get("val"), 8) + 1
        if level is not None and level > 9:
            level = None                                  # outline level 9 = body text
        num = ppr.find("numPr") if ppr is not None else None
        if num is not None and num.find("numId") is not None:
            listed = (num.find("numId").get("val", ""), _int(num.find("ilvl").get("val")) if num.find("ilvl") is not None else 0)
        else:
            listed = self.style_list.get(style)
        inl = _Inline()
        self.runs(el, inl)
        md = inl.md(plain=level is not None)
        if level is not None:
            self.out.heading(level, md)
        elif listed and listed[0] not in ("", "0"):
            self.out.item(max(listed[1], self.style_level.get(style, 0)), self.ordered.get(listed, False), md)
        else:
            self.out.para(md)
        boxes, self.boxes = self.boxes, []
        for box in boxes:
            self.blocks(box)

    def runs(self, parent: ET.Element, inl: _Inline, link: str = "") -> None:
        for c in parent:
            if c.tag == "r":
                self.run(c, inl, link)
            elif c.tag == "hyperlink":
                target, outside, _ = self.rels.get(c.get("r:id", ""), ("", False, ""))
                self.runs(c, inl, _url(target) if outside else link)
            elif c.tag in ("ins", "smartTag", "fldSimple", "customXml", "bdo", "dir"):
                self.runs(c, inl, link)
            elif c.tag == "sdt":
                content = c.find("sdtContent")
                if content is not None:
                    self.runs(content, inl, link)
            elif c.tag in ("oMath", "oMathPara"):
                inl.add("".join(t.text or "" for t in c.iter("t")))

    def run(self, r: ET.Element, inl: _Inline, link: str) -> None:
        props = r.find("rPr")
        if _on(props, "vanish"):
            return
        fmt = (_on(props, "b"), _on(props, "i"), _on(props, "strike"), link)
        for c in r:
            if c.tag == "t":
                inl.add(c.text or "", *fmt)
            elif c.tag == "tab":
                inl.add(" ", *fmt)
            elif c.tag in ("br", "cr"):
                if c.get("type", "textWrapping") == "textWrapping":
                    inl.add("\n")
            elif c.tag == "noBreakHyphen":
                inl.add("-", *fmt)
            elif c.tag in ("drawing", "pict", "object"):
                self.picture(c, inl)
            elif c.tag == "AlternateContent":             # the same shape twice: the modern one, else the fallback
                src = c.find("Choice") if c.find("Choice") is not None else c.find("Fallback")
                for x in src if src is not None else ():
                    if x.tag in ("drawing", "pict", "object"):
                        self.picture(x, inl)

    def picture(self, el: ET.Element, inl: _Inline) -> None:
        ids = [b.get("r:embed", "") for b in el.iter("blip")] + [i.get("r:id", "") for i in el.iter("imagedata")]
        for rid in ids:
            target, outside, _ = self.rels.get(rid, ("", True, ""))
            if not outside:
                inl.raw(self.pack.image(target))
        self.boxes.extend(el.iter("txbxContent"))

    def cell(self, tc: ET.Element) -> str:
        parts = []
        for p in tc.iter("p"):
            inl = _Inline()
            self.runs(p, inl)
            parts.append(inl.md(cell=True))
        self.boxes = []
        return " · ".join(x for x in parts if x)

    def table(self, tbl: ET.Element) -> None:
        trs = tbl.findall("tr")
        if all(len(tr.findall("tc")) <= 1 for tr in trs):    # one column: a frame around text, not a table
            for tr in trs:
                for tc in tr.findall("tc"):
                    self.blocks(tc)
            return
        rows = []
        for tr in trs:
            self.pack.tick()
            cells: list[str] = []
            for tc in tr.findall("tc"):
                cells.append(self.cell(tc))
                span = tc.find("tcPr/gridSpan")
                cells.extend([""] * max(0, min(_int(span.get("val"), 1) if span is not None else 1, 40) - 1))
            rows.append(cells)
        self.out.table(rows)


# ---- PowerPoint ----------------------------------------------------------------------------
class _Pptx:
    def __init__(self, pack: _Pack, out: _Out):
        self.pack, self.out = pack, out

    def read(self) -> None:
        part = self.pack.main("ppt/presentation.xml")
        root, rels = self.pack.xml(part), self.pack.rels(part)
        ids = root.find("sldIdLst") if root is not None else None
        if ids is None:
            raise Unreadable("unsupported", "This document cannot be read")
        slides = [rels[s.get("r:id", "")][0] for s in ids if s.get("r:id", "") in rels]
        if len(slides) > SLIDES_MAX:
            slides, self.pack.truncated = slides[:SLIDES_MAX], True
        for n, name in enumerate(slides, 1):
            self.slide(n, name)

    def slide(self, n: int, name: str) -> None:
        root = self.pack.xml(name)
        tree = root.find("cSld/spTree") if root is not None else None
        if tree is None:
            return
        self.rels = self.pack.rels(name)
        shapes = list(self.shapes(tree))
        title = next((s for s in shapes if s.tag == "sp" and self.role(s) in ("title", "ctrTitle")), None)
        text = " ".join(x for x in (self.inline(p).md(plain=True).replace("\\\n", " ") for p in title.iter("p")) if x) if title is not None else ""
        if n > 1:
            self.out.rule()
        self.out.heading(2, f"{n}\\. {text}" if text else str(n))
        for s in shapes:
            if s is title:
                continue
            if s.tag == "sp":
                if self.role(s) not in ("dt", "ftr", "sldNum"):
                    self.body(s)
            elif s.tag == "pic":
                self.pictures(s)
            elif s.tag == "graphicFrame":
                for tbl in s.iter("tbl"):
                    self.out.table([[" · ".join(x for x in (self.inline(p).md(cell=True) for p in tc.iter("p")) if x)
                                     for tc in tr.findall("tc")] for tr in tbl.findall("tr")])
        notes = self.pack.typed(self.rels, "notesSlide")
        root = self.pack.xml(notes) if notes else None
        for sp in root.iter("sp") if root is not None else ():
            if self.role(sp) == "body":
                self.out.quote("\\\n".join(x for x in (self.inline(p).md() for p in sp.iter("p")) if x))

    def shapes(self, tree: ET.Element):
        for el in tree:
            if el.tag == "grpSp":
                yield from self.shapes(el)
            elif el.tag in ("sp", "pic", "graphicFrame"):
                yield el
            elif el.tag == "AlternateContent":
                src = el.find("Choice") if el.find("Choice") is not None else el.find("Fallback")
                if src is not None:
                    yield from self.shapes(src)

    @staticmethod
    def role(sp: ET.Element) -> str | None:
        """The placeholder a shape fills (`title`, `body`, `subTitle`...; `body` when it only has an index)."""
        ph = sp.find("nvSpPr/nvPr/ph")
        return None if ph is None else ph.get("type", "body")

    def inline(self, p: ET.Element) -> _Inline:
        inl = _Inline()
        for c in p:
            if c.tag in ("r", "fld"):
                props = c.find("rPr")
                link = props.find("hlinkClick") if props is not None else None
                target, outside, _ = self.rels.get(link.get("r:id", ""), ("", False, "")) if link is not None else ("", False, "")
                bold = props is not None and props.get("b") in ("1", "true")
                italic = props is not None and props.get("i") in ("1", "true")
                strike = props is not None and props.get("strike", "noStrike") != "noStrike"
                inl.add("".join(t.text or "" for t in c.findall("t")), bold, italic, strike, _url(target) if outside else "")
            elif c.tag == "br":
                inl.add("\n")
        return inl

    def body(self, sp: ET.Element) -> None:
        role = self.role(sp)
        for p in sp.iter("p"):
            self.pack.tick()
            md = self.inline(p).md()
            props = p.find("pPr")
            bullets = role in ("body", "obj") and not (props is not None and props.find("buNone") is not None)
            if bullets or (props is not None and (props.find("buChar") is not None or props.find("buAutoNum") is not None)):
                self.out.item(_int(props.get("lvl")) if props is not None else 0, props is not None and props.find("buAutoNum") is not None, md)
            else:
                self.out.para(md)
        self.pictures(sp)

    def pictures(self, el: ET.Element) -> None:
        for blip in el.iter("blip"):
            target, outside, _ = self.rels.get(blip.get("r:embed", ""), ("", True, ""))
            if not outside:
                self.out.para(self.pack.image(target))


# ---- OpenDocument --------------------------------------------------------------------------
class _Odf:
    def __init__(self, pack: _Pack, out: _Out | None = None):
        self.pack, self.out = pack, out
        root = pack.xml("content.xml")
        self.body = root.find("body") if root is not None else None
        if self.body is None:
            raise Unreadable("unsupported", "This document cannot be read")
        self.fmt: dict[str, tuple[bool, bool, bool]] = {}   # text style -> bold, italic, strike
        self.numbered: dict[str, set[int]] = {}             # list style -> its numbered levels
        for src in (pack.xml("styles.xml"), root) if out is not None else ():
            for st in src.iter("style") if src is not None else ():
                props = st.find("text-properties")
                if props is not None:
                    f = (props.get("font-weight") == "bold", props.get("font-style") in ("italic", "oblique"),
                         props.get("text-line-through-style", "none") != "none")
                    if any(f):
                        self.fmt[st.get("name", "")] = f
            for ls in src.iter("list-style") if src is not None else ():
                self.numbered[ls.get("name", "")] = {_int(x.get("level"), 1) - 1 for x in ls.findall("list-level-style-number")}

    def inline(self, el: ET.Element, inl: _Inline, fmt: tuple[bool, bool, bool] = (False, False, False), link: str = "") -> _Inline:
        def text(s: str | None) -> None:
            if s:
                inl.add(re.sub(r"\s+", " ", s), *fmt, link)
        text(el.text)
        for c in el:
            if c.tag == "span":
                f = self.fmt.get(c.get("style-name", ""), (False, False, False))
                self.inline(c, inl, (fmt[0] or f[0], fmt[1] or f[1], fmt[2] or f[2]), link)
            elif c.tag == "a":
                self.inline(c, inl, fmt, _url(c.get("href")) or link)
            elif c.tag == "s":
                inl.add(" " * max(1, min(_int(c.get("c"), 1), 100)), *fmt, link)
            elif c.tag == "tab":
                inl.add(" ", *fmt, link)
            elif c.tag == "line-break":
                inl.add("\n")
            elif c.tag == "frame":
                for im in c.findall("image"):
                    inl.raw(self.pack.image(im.get("href", "")))
            elif c.tag not in ("note", "annotation", "tracked-changes", "change-start", "change-end", "bookmark"):
                self.inline(c, inl, fmt, link)
            text(c.tail)
        return inl

    def blocks(self, parent: ET.Element) -> None:
        for el in parent:
            if el.tag == "h":
                self.out.heading(_int(el.get("outline-level"), 1), self.inline(el, _Inline()).md(plain=True))
            elif el.tag == "p":
                self.out.para(self.inline(el, _Inline()).md())
                for box in el.iter("text-box"):
                    self.blocks(box)
            elif el.tag == "list":
                self.list(el, 0, self.numbered.get(el.get("style-name", ""), set()))
            elif el.tag == "table":
                self.table(el)
            elif el.tag in ("section", "text-box", "index-body", "table-of-content", "frame"):
                self.blocks(el)
            elif el.tag == "image":
                self.out.para(self.pack.image(el.get("href", "")))

    def list(self, el: ET.Element, level: int, numbered: set[int]) -> None:
        if level > 20:
            return
        for item in el:
            if item.tag not in ("list-item", "list-header"):
                continue
            for c in item:
                if c.tag in ("p", "h"):
                    self.out.item(level, level in numbered, self.inline(c, _Inline()).md())
                elif c.tag == "list":
                    self.list(c, level + 1, numbered)

    @staticmethod
    def rows(tbl: ET.Element):
        for el in tbl:
            if el.tag == "table-row":
                yield el
            elif el.tag in ("table-header-rows", "table-rows", "table-row-group"):
                yield from _Odf.rows(el)

    def table(self, tbl: ET.Element) -> None:
        rows = []
        for tr in self.rows(tbl):
            self.pack.tick()
            cells: list[str] = []
            for tc in tr:
                if tc.tag == "table-cell":
                    cells.append(" · ".join(x for x in (self.inline(p, _Inline()).md(cell=True) for p in tc.iter("p")) if x))
                elif tc.tag == "covered-table-cell":
                    cells.append("")
            rows.append(cells[:40])
        if all(len(r) <= 1 for r in rows):
            for r in rows:
                self.out.para(r[0] if r else "")
        else:
            self.out.table(rows)

    def text(self) -> None:
        text = self.body.find("text")
        if text is None:
            raise Unreadable("unsupported", "This document cannot be read")
        self.blocks(text)

    def slides(self) -> None:
        deck = self.body.find("presentation")
        if deck is None:
            raise Unreadable("unsupported", "This document cannot be read")
        pages = deck.findall("page")
        if len(pages) > SLIDES_MAX:
            pages, self.pack.truncated = pages[:SLIDES_MAX], True
        for n, page in enumerate(pages, 1):
            frames = [f for f in page if f.tag == "frame"]
            title = next((f for f in frames if f.get("class") == "title"), None)
            text = " ".join(x for x in (self.inline(p, _Inline()).md(plain=True).replace("\\\n", " ") for p in title.iter("p")) if x) if title is not None else ""
            if n > 1:
                self.out.rule()
            self.out.heading(2, f"{n}\\. {text}" if text else str(n))
            for f in frames:
                if f is not title:
                    self.blocks(f)
            notes = page.find("notes")
            for f in notes.iter("text-box") if notes is not None else ():
                self.out.quote("\\\n".join(x for x in (self.inline(p, _Inline()).md() for p in f.iter("p")) if x))

    def sheets(self) -> list[dict]:
        book = self.body.find("spreadsheet")
        if book is None:
            raise Unreadable("unsupported", "This document cannot be read")
        out = []
        tables = book.findall("table")
        if len(tables) > SHEETS_MAX:
            tables, self.pack.truncated = tables[:SHEETS_MAX], True
        for tbl in tables:
            rows: list[list[str]] = []
            cut, blank = False, 0
            for tr in self.rows(tbl):
                self.pack.tick()
                vals: list[str] = []
                gap = 0
                for tc in tr:
                    if tc.tag not in ("table-cell", "covered-table-cell"):
                        continue
                    rep = max(1, _int(tc.get("number-columns-repeated"), 1))
                    text = "\n".join(x for x in ("".join(p.itertext()) for p in tc.findall("p")) if x)[:CELL_MAX]
                    if not text:
                        gap += rep
                        continue
                    if len(vals) + gap >= COLS_MAX:
                        cut = True
                        break
                    vals.extend([""] * gap)
                    gap = 0
                    vals.extend([text] * min(rep, COLS_MAX - len(vals)))
                rep = max(1, _int(tr.get("number-rows-repeated"), 1))
                if not vals:
                    blank += rep
                    continue
                room = ROWS_MAX - len(rows) - blank
                if room <= 0 or self.pack.cells <= 0:
                    cut = True
                    break
                rows.extend([[]] * blank)
                blank = 0
                rep = min(rep, room)
                rows.extend([vals] * rep)
                self.pack.cells -= len(vals) * rep
            out.append({"name": tbl.get("name", ""), "rows": rows, "truncated": cut})
        return out


# ---- Excel ---------------------------------------------------------------------------------
_BUILTIN = {1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 37: "#,##0", 38: "#,##0",
            39: "#,##0.00", 40: "#,##0.00", 41: "#,##0", 42: "#,##0", 43: "#,##0.00", 44: "#,##0.00"}
_DATE_IDS = {*range(14, 23), *range(27, 37), *range(45, 48), *range(50, 59)}
_EPOCH, _EPOCH_1904 = datetime(1899, 12, 30), datetime(1904, 1, 1)


def _number_kind(fid: int, code: str) -> tuple[str, int] | None:
    """How a number format shows a number: ('date', 0), ('percent', decimals), ('fixed', decimals), None = as it is."""
    if fid in _DATE_IDS:
        return ("date", 0)
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", (code or _BUILTIN.get(fid, "")).split(";")[0])
    low = code.lower()
    if not code or "general" in low or "@" in code:
        return None
    digits = re.search(r"[0#?]", code) is not None
    if re.search(r"[dyhs]|mm", low) or ("m" in low and not digits):
        return ("date", 0)
    if not digits or "e+" in low or "e-" in low or "/" in code:
        return None
    m = re.search(r"\.(0+)", code)
    return ("percent" if "%" in code else "fixed", len(m[1]) if m else 0)


def _number(v: str | None, kind: tuple[str, int] | None, date1904: bool) -> str:
    if not v:
        return ""
    try:
        f = float(v)
    except ValueError:
        return v
    if not math.isfinite(f):
        return v
    if kind and kind[0] == "date" and 0 <= f < 2958466:
        at = (_EPOCH_1904 if date1904 else _EPOCH) + timedelta(seconds=round(f * 86400))
        if f < 1:
            return at.strftime("%H:%M:%S" if at.second else "%H:%M")
        return at.strftime("%Y-%m-%d" if f == int(f) else "%Y-%m-%d %H:%M")
    if kind and kind[0] == "percent":
        return f"{f * 100:.{kind[1]}f}%"
    if kind and kind[0] == "fixed":
        return f"{f:.{kind[1]}f}"
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(f) if len(repr(f)) <= 12 else f"{f:.10g}"


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


class _Xlsx:
    def __init__(self, pack: _Pack):
        self.pack = pack
        self.part = pack.main("xl/workbook.xml")
        self.rels = pack.rels(self.part)
        self.shared: list[str] = []
        self.kinds: list[tuple[str, int] | None] = []
        self.date1904 = False

    def strings(self) -> None:
        root = None
        try:
            for ev, el in self.pack.stream(self.pack.typed(self.rels, "sharedStrings", "xl/sharedStrings.xml")):
                if ev == "start":
                    root = el if root is None else root
                    continue
                if _local(el.tag) != "si":
                    continue
                parts = []
                for c in el:
                    self.pack.tick()
                    tag = _local(c.tag)
                    if tag == "t":
                        parts.append(c.text or "")
                    elif tag == "r":
                        parts.extend(t.text or "" for t in c if _local(t.tag) == "t")
                self.shared.append("".join(parts)[:CELL_MAX])
                root.clear()
                if len(self.shared) >= STRINGS_MAX:
                    raise _Full
        except _Full:
            self.pack.truncated = True

    def styles(self) -> None:
        root = self.pack.xml(self.pack.typed(self.rels, "styles", "xl/styles.xml"))
        if root is None:
            return
        codes = {_int(f.get("numFmtId")): f.get("formatCode", "") for f in root.iter("numFmt")}
        xfs = root.find("cellXfs")
        for xf in xfs if xfs is not None else ():
            fid = _int(xf.get("numFmtId"))
            self.kinds.append(_number_kind(fid, codes.get(fid, "")))

    def read(self) -> list[dict]:
        book = self.pack.xml(self.part)
        listed = book.find("sheets") if book is not None else None
        if listed is None:
            raise Unreadable("unsupported", "This document cannot be read")
        props = book.find("workbookPr")
        self.date1904 = props is not None and props.get("date1904") in ("1", "true")
        self.strings()
        self.styles()
        out = []
        for sh in listed:
            target, outside, kind = self.rels.get(sh.get("r:id", ""), ("", True, ""))
            if outside or not kind.endswith("/worksheet") or sh.get("state", "visible") != "visible":
                continue
            if len(out) >= SHEETS_MAX:
                self.pack.truncated = True
                break
            rows, cut = self.sheet(target)
            out.append({"name": sh.get("name", ""), "rows": rows, "truncated": cut})
        return out

    def value(self, c: ET.Element) -> str:
        kind, v, inline = c.get("t", "n"), None, ""
        for ch in c:
            tag = _local(ch.tag)
            if tag == "v":
                v = ch.text
            elif tag == "is":
                inline = "".join(t.text or "" for t in ch.iter() if _local(t.tag) == "t")
        if kind == "s":
            i = _int(v, -1)
            return self.shared[i] if 0 <= i < len(self.shared) else ""
        if kind == "inlineStr":
            return inline[:CELL_MAX]
        if kind == "b":
            return "TRUE" if v == "1" else "FALSE" if v else ""
        if kind in ("str", "e", "d"):
            return (v or "")[:CELL_MAX]
        s = _int(c.get("s"), -1)
        return _number(v, self.kinds[s] if 0 <= s < len(self.kinds) else None, self.date1904)

    def sheet(self, name: str) -> tuple[list[list[str]], bool]:
        rows: list[list[str]] = []
        data, cut = None, False
        try:
            for ev, el in self.pack.stream(name):
                tag = _local(el.tag)
                if ev == "start":
                    data = el if tag == "sheetData" else data
                    continue
                if tag == "sheetData":
                    break
                if tag != "row":
                    continue
                vals: list[str] = []
                for c in el:
                    self.pack.tick()                      # a row of empty cells by the million writes nothing
                    if _local(c.tag) != "c":
                        continue
                    ref = c.get("r")
                    col = _col(ref) if ref else len(vals)
                    text = self.value(c)
                    if not text or col < len(vals):
                        continue
                    if col >= COLS_MAX:
                        cut = True
                        break
                    vals.extend([""] * (col - len(vals)))
                    vals.append(text)
                at = max(_int(el.get("r"), len(rows) + 1) - 1, len(rows))
                (data if data is not None else el).clear()   # the rows read do not pile up in memory
                if not vals:
                    continue
                if at >= ROWS_MAX or self.pack.cells <= 0:
                    raise _Full
                rows.extend([[]] * (at - len(rows)))
                rows.append(vals)
                self.pack.cells -= len(vals)
        except _Full:
            cut = True
        return rows, cut


# ---- entry points --------------------------------------------------------------------------
def kind(path: Path) -> str | None:
    """`text`, `sheets` or `slides` for a document this module reads (by its extension), else None."""
    return KINDS.get(path.suffix.lower())


def read(path: Path) -> dict:
    """{"type", "markdown" (text, slides) or "sheets": [{"name", "rows", "truncated"}], "truncated"}.
    Raises Unreadable."""
    shape = kind(path)
    if shape is None:
        raise Unreadable("unsupported", "Not a document that can be shown")
    pack = _Pack(path)
    odf = path.suffix.lower() in (".odt", ".ods", ".odp")
    try:
        if shape == "sheets":
            try:
                sheets = _Odf(pack).sheets() if odf else _Xlsx(pack).read()
            except _Full:                      # out of time before the first sheet was whole
                sheets, pack.truncated = [], True
            return {"type": shape, "sheets": sheets, "truncated": pack.truncated or any(s["truncated"] for s in sheets)}
        out = _Out(pack)
        try:
            if odf:
                doc = _Odf(pack, out)
                doc.text() if shape == "text" else doc.slides()
            else:
                (_Docx if shape == "text" else _Pptx)(pack, out).read()
        except _Full:
            pack.truncated = True
        return {"type": shape, "markdown": out.text(), "truncated": pack.truncated}
    except RecursionError:
        raise Unreadable("unsupported", "This document cannot be read") from None
    finally:
        pack.close()


def media(path: Path, name: str) -> tuple[bytes, str]:
    """A picture of a document, by the name its Markdown gives: (bytes, mime). Raises Unreadable."""
    mime = IMAGE_TYPES.get(posixpath.splitext(name)[1].lower())
    if mime is None or kind(path) is None:
        raise Unreadable("unsupported", "Not a picture of this document")
    pack = _Pack(path)
    try:
        data = pack.data(name, MEDIA_MAX)
    finally:
        pack.close()
    if data is None:
        raise Unreadable("unsupported", "Not a picture of this document")
    return data, mime
