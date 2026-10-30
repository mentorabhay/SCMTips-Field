"""The audit report PDF is a real PDF: header, objects at the offsets the xref table claims, pages."""

from __future__ import annotations

import re

from field_worker.jobs.pdf import LINES_PER_PAGE, text_pdf
from hypothesis import given, settings
from hypothesis import strategies as st


@settings(max_examples=40, deadline=None)
@given(st.lists(st.text(max_size=80), max_size=150))
def test_t4_060_pdf_structure_is_valid(lines: list[str]) -> None:
    pdf = text_pdf(lines, title="t")
    assert pdf.startswith(b"%PDF-1.4\n") and pdf.rstrip().endswith(b"%%EOF")
    xref_at = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
    assert pdf[xref_at:].startswith(b"xref\n")
    entries = re.findall(rb"(\d{10}) 00000 n \n", pdf[xref_at:])
    for n, off in enumerate(entries, start=1):
        assert pdf[int(off):].startswith(f"{n} 0 obj\n".encode())
    pages = max(1, -(-len(lines) // LINES_PER_PAGE))
    assert pdf.count(b"/Type /Page ") == pages
    assert f"/Count {pages}".encode() in pdf


def test_t4_060_text_is_escaped() -> None:
    pdf = text_pdf(["a (b) \\ c", "ünï"], title="x")
    assert b"(a \\(b\\) \\\\ c) '" in pdf
