# -*- coding: utf-8 -*-
"""Smoke tests — every output format produces a non-empty,
format-shaped artifact on a minimal harness.

These are the cheapest tests in the suite. If any of them fail, the
WireViz CLI is unusable for that format.
"""

from pathlib import Path

import pytest

from wireviz.wireviz import parse


@pytest.mark.parametrize(
    "fmt, ext, signature",
    [
        ("svg", "svg", b"<?xml"),
        ("png", "png", b"\x89PNG\r\n"),
        ("gv", "gv", b"graph {"),
        ("tsv", "bom.tsv", b"Id\t"),  # BOM TSV header
        ("html", "html", b"<!DOCTYPE html>"),
        ("pdf", "pdf", b"%PDF-"),
    ],
)
def test_each_format_renders(minimal_yaml: Path, workdir: Path, fmt, ext, signature):
    """Every supported output format produces a file with the right
    magic-bytes signature. Catches: missing format codes, render-path
    regressions, broken graphviz piping."""
    parse(
        minimal_yaml,
        output_formats=(fmt,),
        output_dir=workdir,
        output_name="out",
        embed_yaml=False,
    )
    artifact = workdir / f"out.{ext}"
    assert artifact.exists(), f"{ext} not produced"
    head = artifact.read_bytes()[: len(signature)]
    assert head == signature, f"unexpected {ext} signature: {head!r}"


def test_multi_format_one_call(minimal_yaml: Path, workdir: Path):
    """One ``parse()`` call writes every requested format atomically."""
    parse(
        minimal_yaml,
        output_formats=("svg", "png", "gv", "tsv", "html", "pdf"),
        output_dir=workdir,
        output_name="multi",
        embed_yaml=False,
    )
    for ext in ("svg", "png", "gv", "bom.tsv", "html", "pdf"):
        assert (workdir / f"multi.{ext}").exists(), f"{ext} missing"


def test_minimal_gv_is_valid_graphviz(minimal_yaml: Path, workdir: Path):
    """The .gv source must parse as valid Graphviz — i.e. balanced
    braces, well-formed graph header. We don't shell out to ``dot -c``;
    a structural check on the source string is enough."""
    parse(
        minimal_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="m",
        embed_yaml=False,
    )
    gv = (workdir / "m.gv").read_text()
    assert gv.startswith("graph {")
    assert gv.rstrip().endswith("}")
    # Nodes for X1 and W1 must both appear
    assert "X1 [label=" in gv
    assert "W1 [label=" in gv


def test_html_embeds_svg_inline(minimal_yaml: Path, workdir: Path):
    """HTML output embeds the SVG inline (not a sibling-file <img>),
    so a single .html is self-contained."""
    parse(
        minimal_yaml,
        output_formats=("html",),
        output_dir=workdir,
        output_name="h",
        embed_yaml=False,
    )
    html = (workdir / "h.html").read_text()
    assert "<svg " in html, "HTML output should contain inline SVG"
    assert "<!-- %diagram% -->" not in html, "diagram placeholder unresolved"


def test_tsv_has_header_and_one_data_row(minimal_yaml: Path, workdir: Path):
    """The BOM TSV always starts with a header row and contains at
    least one component row for the cable in this minimal harness."""
    parse(
        minimal_yaml,
        output_formats=("tsv",),
        output_dir=workdir,
        output_name="b",
        embed_yaml=False,
    )
    rows = (workdir / "b.bom.tsv").read_text().splitlines()
    assert len(rows) >= 2, "expected header + at least one data row"
    # Header line: tab-separated column names starting with "Id"
    assert rows[0].split("\t")[0] == "Id", "first row should be the column header"
    # Cable W1 should appear in some data row
    assert any("W1" in r or "Cable" in r for r in rows[1:])
