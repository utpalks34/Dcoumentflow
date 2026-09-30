"""Hand-built minimal PDF bytes for tests -- no fixture files with real
invoice content are ever committed (docs/06_LLM_Instructions.md, Hard rule 8).
"""

from __future__ import annotations


def build_minimal_pdf(
    content_stream: bytes,
    *,
    include_font: bool = True,
    producer: str | None = None,
    creator: str | None = None,
    n_pages: int = 1,
) -> bytes:
    """A minimal, valid single- or multi-page PDF with one shared content
    stream, for exercising page-count / text-layer / metadata detection."""
    info_parts = []
    if producer is not None:
        info_parts.append(f"/Producer ({producer})")
    if creator is not None:
        info_parts.append(f"/Creator ({creator})")

    objects: list[bytes] = []
    page_obj_nums = list(range(3, 3 + n_pages))
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    )  # 2

    content_obj_num = 3 + n_pages
    font_obj_num = content_obj_num + 1
    resources = f"<< /Font << /F1 {font_obj_num} 0 R >> >>" if include_font else "<< >>"
    for _ in range(n_pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources {resources} /Contents {content_obj_num} 0 R >>"
            ).encode()
        )  # 3..3+n_pages-1

    stream_obj = (
        b"<< /Length %d >>\nstream\n" % len(content_stream)
    ) + content_stream + b"\nendstream"
    objects.append(stream_obj)  # content_obj_num

    if include_font:
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # font_obj_num

    info_obj_num = None
    if info_parts:
        info_obj_num = len(objects) + 1
        objects.append(("<< " + " ".join(info_parts) + " >>").encode())

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_offset = len(pdf)
    n_objects = len(objects) + 1
    pdf += f"xref\n0 {n_objects}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()

    trailer = f"<< /Size {n_objects} /Root 1 0 R"
    if info_obj_num is not None:
        trailer += f" /Info {info_obj_num} 0 R"
    trailer += " >>\n"

    pdf += (
        b"trailer\n"
        + trailer.encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return bytes(pdf)


def pdf_with_text(text: str = "Hello Invoice", n_pages: int = 1) -> bytes:
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    return build_minimal_pdf(content, include_font=True, n_pages=n_pages)


def pdf_scanned_blank(n_pages: int = 1) -> bytes:
    return build_minimal_pdf(b"", include_font=False, n_pages=n_pages)


def pdf_with_metadata(producer: str, creator: str, text: str = "Hello Invoice") -> bytes:
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    return build_minimal_pdf(content, include_font=True, producer=producer, creator=creator)
