"""Write small synthetic PDFs used by the examples and the screenshot."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.xmp import XmpInformation


def write_samples(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write(
        directory / "project-overview.pdf",
        metadata={
            "/Title": "Project overview",
            "/Author": "Documentation Team",
            "/Subject": "Synthetic example for the compliance checker",
            "/Keywords": "overview",
            "/Classification": "Public",
        },
        pdfa=("2", "B"),
    )
    _write(
        directory / "quarterly-update.pdf",
        metadata={
            "/Title": "Quarterly update",
            "/Author": "Documentation Team",
            "/Classification": "Secret",
        },
        pdfa=None,
    )


def _write(path: Path, metadata: dict[str, str], pdfa: tuple[str, str] | None) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata(metadata)
    if pdfa is not None:
        xmp = XmpInformation.create()
        xmp.pdfaid_part = pdfa[0]
        xmp.pdfaid_conformance = pdfa[1]
        writer.xmp_metadata = xmp
    with path.open("wb") as handle:
        writer.write(handle)
