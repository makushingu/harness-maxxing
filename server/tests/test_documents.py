"""Office documents and PDF pages in the Files viewer (maxxing/documents.py, /api/files/doc, /api/files/pdf)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from maxxing import documents

from test_files import tree  # noqa: F401  (fixture)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")


def pack(path: Path, parts: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def rels(*items: tuple[str, str, str, bool]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{REL}/{kind}" Target="{target}"{" TargetMode=\"External\"" if outside else ""}/>'
                   for i, kind, target, outside in items)
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def docx(path: Path, body: str, **extra: str | bytes) -> Path:
    return pack(path, {
        "_rels/.rels": rels(("rId1", "officeDocument", "word/document.xml", False)),
        "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>",
        **extra})


def test_a_word_document_becomes_markdown(tmp_path):
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Titre1"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>Budget *2026*</w:t></w:r></w:p>'
        '<w:p><w:r><w:t xml:space="preserve">Total: </w:t></w:r><w:r><w:rPr><w:b/><w:i w:val="0"/></w:rPr><w:t>12 k</w:t></w:r>'
        '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> net</w:t></w:r><w:r><w:br/><w:t>- not a list &lt;b&gt;</w:t></w:r>'
        '<w:del><w:r><w:delText>gone</w:delText></w:r></w:del></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>one</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="2"/></w:numPr></w:pPr><w:r><w:t>sub</w:t></w:r></w:p>'
        '<w:p><w:hyperlink r:id="rId5"><w:r><w:t>site</w:t></w:r></w:hyperlink><w:hyperlink r:id="rId6"><w:r><w:t>bad</w:t></w:r></w:hyperlink></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>A|B</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p><w:p><w:r><w:t>y</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:drawing><a:blip r:embed="rId7"/></w:drawing></w:r><w:r><w:drawing><a:blip r:embed="rId8"/></w:drawing></w:r></w:p>')
    f = docx(tmp_path / "a.docx", body, **{
        "word/_rels/document.xml.rels": rels(
            ("rId2", "styles", "styles.xml", False), ("rId3", "numbering", "numbering.xml", False),
            ("rId5", "hyperlink", "https://example.com/a (b)", True), ("rId6", "hyperlink", "javascript:alert(1)", True),
            ("rId7", "image", "media/image1.png", False), ("rId8", "image", "media/image2.emf", False)),
        "word/styles.xml": f'<w:styles {W}><w:style w:styleId="Titre1"><w:name w:val="heading 1"/></w:style></w:styles>',
        "word/numbering.xml": f'<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
                              '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                              '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>',
        "word/media/image1.png": PNG, "word/media/image2.emf": b"emf"})
    r = documents.read(f)
    assert r["type"] == "text" and not r["truncated"]
    assert r["markdown"] == (
        "# Budget \\*2026\\*\n\n"
        "Total: **12 k** *net*\\\n\\- not a list \\<b\\>\n\n"
        "1. one\n    - sub\n\n"
        "[site](https://example.com/a%20%28b%29)bad\n\n"
        "| Name | A\\|B |\n| --- | --- |\n| x · y |   |\n\n"
        "![](word/media/image1.png)\n")
    assert documents.media(f, "word/media/image1.png") == (PNG, "image/png")
    for name in ("word/document.xml", "word/media/image2.emf", "word/media/none.png", "../a.png"):
        with pytest.raises(documents.Unreadable):
            documents.media(f, name)


S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def xlsx(path: Path, rows: str, sheets: str = '<sheet name="Sales" sheetId="1" r:id="rId1"/>') -> Path:
    return pack(path, {
        "_rels/.rels": rels(("rId1", "officeDocument", "xl/workbook.xml", False)),
        "xl/workbook.xml": f"<workbook {S}><sheets>{sheets}</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": rels(("rId1", "worksheet", "worksheets/sheet1.xml", False), ("rId2", "worksheet", "worksheets/sheet1.xml", False),
                                           ("rId3", "sharedStrings", "sharedStrings.xml", False), ("rId4", "styles", "styles.xml", False)),
        "xl/sharedStrings.xml": f"<sst {S}><si><t>Name</t></si><si><r><t>Ri</t></r><r><t>ch</t></r><rPh><t>no</t></rPh></si></sst>",
        "xl/styles.xml": f'<styleSheet {S}><numFmts><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/><numFmt numFmtId="165" formatCode="0.0\\ &quot;kg&quot;"/></numFmts>'
                         '<cellXfs><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="10"/><xf numFmtId="165"/><xf numFmtId="20"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>{rows}</sheetData></worksheet>"})


def test_a_workbook_becomes_the_rows_of_its_visible_sheets(tmp_path):
    f = xlsx(tmp_path / "a.xlsx",
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="D1" t="inlineStr"><is><t>in</t></is></c></row>'
             '<row r="3"><c r="A3" s="1"><v>46023</v></c><c r="B3" s="2"><v>0.125</v></c><c r="C3" s="3"><v>2.25</v></c>'
             '<c r="D3" s="4"><v>0.75</v></c><c r="E3"><v>0.30000000000000004</v></c><c r="F3" t="b"><v>1</v></c><c r="G3"><v>42</v></c>'
             '<c r="H3" t="str"><f>A1</f><v>Name</v></c></row><row r="4"/>',
             '<sheet name="Sales" sheetId="1" r:id="rId1"/><sheet name="Hidden" sheetId="2" state="hidden" r:id="rId2"/>')
    r = documents.read(f)
    assert r["type"] == "sheets" and not r["truncated"] and [s["name"] for s in r["sheets"]] == ["Sales"]
    assert r["sheets"][0]["rows"] == [["Name", "Rich", "", "in"], [],
                                      ["2026-01-01", "12.50%", "2.2", "18:00", "0.3", "TRUE", "42", "Name"]]


def test_a_sheet_larger_than_the_limits_is_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "ROWS_MAX", 20)
    rows = "".join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c><c r="ZZ{i}"><v>1</v></c></row>' for i in range(1, 200))
    r = documents.read(xlsx(tmp_path / "big.xlsx", rows))
    assert r["truncated"] and r["sheets"][0]["truncated"] and r["sheets"][0]["rows"][:2] == [["1"], ["2"]] and len(r["sheets"][0]["rows"]) == 20
    # a row number far away (a cell written at the bottom of the sheet) does not fill the answer with empty rows
    r = documents.read(xlsx(tmp_path / "far.xlsx", '<row r="1"><c r="A1"><v>1</v></c></row><row r="1048576"><c r="A1048576"><v>2</v></c></row>'))
    assert r["sheets"][0]["rows"] == [["1"]] and r["truncated"]


P = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def test_a_presentation_becomes_its_slides(tmp_path):
    def slide(shapes: str) -> str:
        return f"<p:sld {P}><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>"

    def sp(ph: str, paras: str) -> str:
        return f"<p:sp><p:nvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:txBody>{paras}</p:txBody></p:sp>"
    f = pack(tmp_path / "a.pptx", {
        "_rels/.rels": rels(("rId1", "officeDocument", "ppt/presentation.xml", False)),
        "ppt/presentation.xml": f'<p:presentation {P}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": rels(("rId1", "slide", "slides/slide1.xml", False), ("rId2", "slide", "slides/slide2.xml", False)),
        "ppt/slides/slide2.xml": slide(sp('<p:ph type="ctrTitle"/>', "<a:p><a:r><a:t>Road</a:t></a:r><a:r><a:t>map</a:t></a:r></a:p>")
                                       + sp('<p:ph idx="1"/>', '<a:p><a:r><a:rPr b="1"/><a:t>First</a:t></a:r></a:p><a:p><a:pPr lvl="1"/><a:r><a:t>Detail</a:t></a:r></a:p>')
                                       + sp('<p:ph type="sldNum"/>', "<a:p><a:fld><a:t>1</a:t></a:fld></a:p>")),
        "ppt/slides/_rels/slide2.xml.rels": rels(("rId1", "notesSlide", "../notesSlides/n1.xml", False)),
        "ppt/notesSlides/n1.xml": f"<p:notes {P}><p:cSld><p:spTree>{sp('<p:ph type=\"body\"/>', '<a:p><a:r><a:t>Say hello</a:t></a:r></a:p>')}</p:spTree></p:cSld></p:notes>",
        "ppt/slides/slide1.xml": slide(sp("", "<a:p><a:r><a:t>Free text</a:t></a:r></a:p>")
                                       + '<p:pic><p:blipFill><a:blip r:embed="rId9"/></p:blipFill></p:pic>'),
        "ppt/slides/_rels/slide1.xml.rels": rels(("rId9", "image", "../media/i.png", False)),
        "ppt/media/i.png": PNG})
    r = documents.read(f)
    assert r["type"] == "slides" and r["markdown"] == (
        "## 1\\. Roadmap\n\n- **First**\n    - Detail\n\n> Say hello\n\n---\n\n## 2\n\nFree text\n\n![](ppt/media/i.png)\n")


ODF = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
       'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
       'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"')


def odf(path: Path, body: str, styles: str = "") -> Path:
    return pack(path, {"content.xml": f"<office:document-content {ODF}><office:automatic-styles>{styles}</office:automatic-styles>"
                                      f"<office:body>{body}</office:body></office:document-content>", "Pictures/p.png": PNG})


def test_opendocument_text_sheets_and_slides(tmp_path):
    r = documents.read(odf(tmp_path / "a.odt", (
        '<office:text><text:h text:outline-level="2">Plan</text:h>'
        '<text:p>Some <text:span text:style-name="T1">bold</text:span>\n   text<text:s text:c="3"/>and a <text:a xlink:href="https://example.com">link</text:a>'
        '<text:note><text:p>footnote</text:p></text:note></text:p>'
        '<text:list text:style-name="L1"><text:list-item><text:p>a</text:p><text:list><text:list-item><text:p>b</text:p></text:list-item></text:list></text:list-item></text:list>'
        '<table:table><table:table-header-rows><table:table-row><table:table-cell><text:p>K</text:p></table:table-cell><table:table-cell><text:p>V</text:p></table:table-cell></table:table-row></table:table-header-rows>'
        '<table:table-row><table:table-cell><text:p>k</text:p></table:table-cell><table:covered-table-cell/></table:table-row></table:table>'
        '<text:p><draw:frame><draw:image xlink:href="Pictures/p.png"/></draw:frame></text:p></office:text>'),
        '<style:style style:name="T1" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>'
        '<text:list-style style:name="L1"><text:list-level-style-number text:level="1"/><text:list-level-style-bullet text:level="2"/></text:list-style>'))
    assert r["markdown"] == ("## Plan\n\nSome **bold** text and a [link](https://example.com)\n\n1. a\n    - b\n\n"
                             "| K | V |\n| --- | --- |\n| k |   |\n\n![](Pictures/p.png)\n")
    # a sheet "filled" to the last row and column by repeats is only its real cells
    r = documents.read(odf(tmp_path / "a.ods", (
        '<office:spreadsheet><table:table table:name="S1">'
        '<table:table-row><table:table-cell><text:p>a</text:p></table:table-cell><table:table-cell table:number-columns-repeated="2"/>'
        '<table:table-cell table:number-columns-repeated="2"><text:p>d</text:p></table:table-cell><table:table-cell table:number-columns-repeated="16000"/></table:table-row>'
        '<table:table-row table:number-rows-repeated="2"/><table:table-row><table:table-cell><text:p>z</text:p></table:table-cell></table:table-row>'
        '<table:table-row table:number-rows-repeated="1048000"><table:table-cell table:number-columns-repeated="16384"/></table:table-row>'
        '</table:table></office:spreadsheet>')))
    assert r == {"type": "sheets", "truncated": False, "sheets": [{"name": "S1", "truncated": False, "rows": [["a", "", "", "d", "d"], [], [], ["z"]]}]}
    r = documents.read(odf(tmp_path / "a.odp", (
        '<office:presentation><draw:page><draw:frame presentation:class="title"><draw:text-box><text:p>Hello</text:p></draw:text-box></draw:frame>'
        '<draw:frame><draw:text-box><text:list><text:list-item><text:p>point</text:p></text:list-item></text:list></draw:text-box></draw:frame>'
        '<presentation:notes><draw:frame><draw:text-box><text:p>note</text:p></draw:text-box></draw:frame></presentation:notes></draw:page>'
        '<draw:page><draw:frame><draw:image xlink:href="Pictures/p.png"/></draw:frame></draw:page></office:presentation>')))
    assert r["markdown"] == "## 1\\. Hello\n\n- point\n\n> note\n\n---\n\n## 2\n\n![](Pictures/p.png)\n"


def test_documents_that_cannot_or_must_not_be_read(tmp_path, monkeypatch):
    def code(f: Path) -> str:
        with pytest.raises(documents.Unreadable) as e:
            documents.read(f)
        return e.value.code
    (tmp_path / "old.docx").write_bytes(b"\xd0\xcf\x11\xe0 an old or encrypted Word file")
    assert code(tmp_path / "old.docx") == "unsupported"
    assert code(pack(tmp_path / "empty.docx", {"x": "y"})) == "unsupported"
    (tmp_path / "a.doc").write_bytes(b"x")
    assert code(tmp_path / "a.doc") == "unsupported"
    # a DTD (entity expansion, "billion laughs") is refused before any parsing
    bomb = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    assert code(pack(tmp_path / "dtd.docx", {"word/document.xml": f"{bomb}<w:document {W}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>"})) == "unsupported"
    f = xlsx(tmp_path / "dtd.xlsx", "")
    with zipfile.ZipFile(f, "a") as z:
        z.writestr("xl/worksheets/sheet9.xml", "x")
    assert code(pack(tmp_path / "dtd2.xlsx", {"xl/workbook.xml": f'<workbook {S}><sheets><sheet name="s" r:id="rId1"/></sheets></workbook>',
                                              "xl/_rels/workbook.xml.rels": rels(("rId1", "worksheet", "worksheets/s.xml", False)),
                                              "xl/worksheets/s.xml": f"{bomb}<worksheet {S}><sheetData/></worksheet>"})) == "unsupported"
    # a part that inflates past the limit is not read
    monkeypatch.setattr(documents, "PART_MAX", 4096)
    assert code(docx(tmp_path / "huge.docx", "<w:p><w:r><w:t>" + "a" * 5000 + "</w:t></w:r></w:p>")) == "too_large"
    monkeypatch.undo()
    # the answer has a size: the rest is cut, and said so
    monkeypatch.setattr(documents, "TEXT_MAX", 300)
    r = documents.read(docx(tmp_path / "long.docx", "".join(f"<w:p><w:r><w:t>paragraph {i}</w:t></w:r></w:p>" for i in range(500))))
    assert r["truncated"] and r["markdown"].startswith("paragraph 0\n\nparagraph 1\n") and len(r["markdown"]) <= 300


def test_document_routes(client, tree):  # noqa: F811
    f = docx(tree / "a.docx", '<w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:drawing><a:blip r:embed="rId7"/></w:drawing></w:r></w:p>', **{
        "word/_rels/document.xml.rels": rels(("rId7", "image", "media/image1.png", False)), "word/media/image1.png": PNG})
    r = client.get("/api/files/doc", params={"path": str(f)})
    assert r.status_code == 200
    assert r.json() | {"mtime": 0} == {"path": str(f), "mtime": 0, "size": f.stat().st_size, "type": "text", "truncated": False,
                                       "markdown": "Hello![](word/media/image1.png)\n"}
    r = client.get("/api/files/doc/media", params={"path": str(f), "name": "word/media/image1.png"})
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/files/doc/media", params={"path": str(f), "name": "word/document.xml"}).status_code == 404
    assert client.get("/api/files/doc", params={"path": str(tree / "b.txt")}).status_code == 415
    assert client.get("/api/files/doc", params={"path": str(tree / "none.docx")}).status_code == 404
    assert client.get("/api/files/doc", params={"path": "/etc/passwd"}).status_code == 403
    (tree / "bad.xlsx").write_bytes(b"not a zip")
    r = client.get("/api/files/doc", params={"path": str(tree / "bad.xlsx")})
    assert r.status_code == 415 and r.json()["error"] == "unsupported"


def pdf(path: Path, pages: int, box: str = "0 0 200 400") -> Path:
    """A PDF of empty pages, valid enough for poppler."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Count {pages} /Kids [{' '.join(f'{3 + i} 0 R' for i in range(pages))}] >>".encode()]
    objs += [f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] >>".encode() for _ in range(pages)]
    out, at = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        at.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{a:010d} 00000 n \n".encode() for a in at)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


@pytest.mark.skipif(not all(shutil.which(x) for x in ("pdfinfo", "pdftoppm", "ffmpeg")), reason="poppler-utils or ffmpeg not installed")
def test_pdf_pages(client, tree, mx):  # noqa: F811
    f = pdf(tree / "a.pdf", 3)
    r = client.get("/api/files/pdf", params={"path": str(f)}).json()
    assert r["pages"] == 3 and r["ratio"] == 2.0 and r["mtime"] == f.stat().st_mtime
    r = client.get("/api/files/pdf/page", params={"path": str(f), "n": 2, "w": 500, "v": "1"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and "immutable" in r.headers["cache-control"]
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WEBP"
    kept = list((mx["state"] / "thumbs").glob("*.webp"))
    assert len(kept) == 1                                           # 500 -> the 640 px page, kept
    assert client.get("/api/files/pdf/page", params={"path": str(f), "n": 2, "w": 640}).content == r.content
    assert len(list((mx["state"] / "thumbs").glob("*.webp"))) == 1
    assert client.get("/api/files/pdf/page", params={"path": str(f), "n": 9}).status_code == 415      # no such page
    assert client.get("/api/files/pdf/page", params={"path": str(f), "n": 0}).status_code == 422
    assert client.get("/api/files/pdf/page", params={"path": str(tree / "b.txt")}).status_code == 404
    (tree / "broken.pdf").write_bytes(b"%PDF-1.4 nothing")
    assert client.get("/api/files/pdf", params={"path": str(tree / "broken.pdf")}).status_code == 415
    assert client.get("/api/files/pdf", params={"path": str(tree / "none.pdf")}).status_code == 404


def test_pdf_pages_without_the_tools(client, tree, monkeypatch):  # noqa: F811
    """No poppler-utils: the viewer is told (415) and keeps the browser's own PDF viewer."""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    assert client.get("/api/files/pdf", params={"path": str(pdf(tree / "a.pdf", 1))}).status_code == 415


def test_the_time_limit_is_checked_while_nothing_is_written(tmp_path, monkeypatch):
    """Empty paragraphs or empty cells by the million write no text: the deadline is still checked."""
    monkeypatch.setattr(documents, "TIME_S", -1.0)
    r = documents.read(docx(tmp_path / "empty.docx", "<w:p/>" * 500))
    assert r["truncated"]
    r = documents.read(xlsx(tmp_path / "empty.xlsx", '<row r="1">' + "<c/>" * 500 + "</row>"))
    assert r["truncated"]
