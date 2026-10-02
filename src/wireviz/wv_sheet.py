# -*- coding: utf-8 -*-
"""Print-ready sheet PDF: the HTML output rendered to PDF (upstream #32, #304).

Uses WeasyPrint (>= 70), an optional dependency: ``pip install "wireviz[pdf]"``.
WeasyPrint also needs the Pango system library (on macOS with Homebrew,
``brew install pango`` and, if Python cannot find it,
``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib``).

Everything the HTML needs is inline (SVG diagram, ``data:`` images), so
WeasyPrint may fetch ``data:`` URLs only: rendering a sheet never reads a
file or the network. With ``timeout`` set (untrusted mode), WeasyPrint
runs in a child process that is stopped after ``timeout`` seconds.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from wireviz.wv_errors import WireVizRenderError


class SheetPdfUnavailable(WireVizRenderError):
    """WeasyPrint is not installed or cannot load its system libraries."""


def _weasyprint():
    try:
        import weasyprint
        from weasyprint.urls import URLFetcher
    except Exception as exc:  # ImportError, or OSError for missing Pango
        raise SheetPdfUnavailable(
            'The sheet PDF format needs WeasyPrint 70 or later: pip install "wireviz[pdf]" '
            f"(and the Pango library). Import failed: {exc}"
        ) from exc
    return weasyprint, URLFetcher


def _render(html: str) -> bytes:
    weasyprint, URLFetcher = _weasyprint()
    fetcher = URLFetcher(allowed_protocols={"data"}, allow_redirects=False)
    return weasyprint.HTML(string=html, url_fetcher=fetcher).write_pdf()


def _limit_memory() -> None:  # runs in the child before exec (POSIX)
    try:
        import resource

        limit = 2 * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        pass  # not supported on this platform (e.g. macOS); timeout still applies


def html_to_pdf(html: str, timeout: Optional[float] = None) -> bytes:
    """Render the WireViz HTML output to a PDF document."""
    if timeout is None:
        return _render(html)
    _weasyprint()  # fail early, with the install hint, in this process
    # -c, with sys.path[0] set to this package's root: "python -m" would put
    # the working directory first and could import a different "wireviz".
    package_root = str(Path(__file__).resolve().parent.parent)
    code = (
        "import sys; sys.path[0] = " + repr(package_root) + "; "
        "from wireviz.wv_sheet import _main; _main()"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            input=html.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            preexec_fn=_limit_memory if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise WireVizRenderError(
            f"The sheet PDF did not finish within {timeout} s"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise WireVizRenderError(
            "The sheet PDF failed" + (f": {detail[-1]}" if detail else "")
        )
    return result.stdout


def _main() -> None:  # child process for html_to_pdf(timeout=...)
    sys.stdout.buffer.write(_render(sys.stdin.buffer.read().decode("utf-8")))
