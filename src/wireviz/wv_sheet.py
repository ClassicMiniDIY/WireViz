# -*- coding: utf-8 -*-
"""Print-ready sheet PDF: the HTML output rendered to PDF (upstream #32, #304).

Uses WeasyPrint, an optional dependency: ``pip install "wireviz[pdf]"``.
WeasyPrint also needs the Pango system library (on macOS with Homebrew,
``brew install pango`` and, if Python cannot find it,
``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib``).

The HTML already holds everything inline (SVG diagram, data-URI images),
so WeasyPrint gets a URL fetcher that refuses every URL: rendering a
sheet never reads a file or the network.
"""


class SheetPdfUnavailable(RuntimeError):
    """WeasyPrint is not installed or cannot load its system libraries."""


def _refuse_urls(url, *args, **kwargs):
    raise ValueError(f"sheet PDF: external resources are not loaded ({url[:60]})")


def html_to_pdf(html: str) -> bytes:
    """Render the WireViz HTML output to a PDF document."""
    try:
        import weasyprint
    except Exception as exc:  # ImportError, or OSError for missing Pango
        raise SheetPdfUnavailable(
            'The sheet PDF format needs WeasyPrint: pip install "wireviz[pdf]" '
            f"(and the Pango library). Import failed: {exc}"
        ) from exc
    return weasyprint.HTML(string=html, url_fetcher=_refuse_urls).write_pdf()
