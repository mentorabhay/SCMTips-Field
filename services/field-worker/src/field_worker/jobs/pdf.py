"""Minimal, valid PDF 1.4 writer for plain-text reports (no third-party dependency).

Writes Helvetica text lines on A4 pages (54 lines per page), with a correct cross-reference table,
so any PDF reader opens it. Non-Latin-1 characters are replaced with '?'.
"""

from __future__ import annotations

LINES_PER_PAGE = 54
FONT_SIZE = 9
WIDTH, HEIGHT = 595, 842  # A4 in points


def _escape(text: str) -> str:
    t = text.encode("latin-1", "replace").decode("latin-1")
    return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(lines: list[str], title: str = "Report") -> bytes:
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)] or [[]]
    objs: list[bytes] = []  # object n is objs[n-1]
    # 1 catalog, 2 pages, 3 font, 4 info; then per page: page object + content stream
    page_ids = [5 + 2 * i for i in range(len(pages))]
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(f"<< /Title ({_escape(title)}) /Producer (SCMTips Field) >>".encode("latin-1"))
    for i, page in enumerate(pages):
        body = [f"BT /F1 {FONT_SIZE} Tf 40 {HEIGHT - 50} Td {FONT_SIZE + 4} TL"]
        body += [f"({_escape(ln[:150])}) '" for ln in page]
        body.append("ET")
        stream = "\n".join(body).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body_bytes in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body_bytes + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 4 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
