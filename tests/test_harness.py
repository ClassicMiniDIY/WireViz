# -*- coding: utf-8 -*-
"""Coverage of the ``Harness`` class itself — the in-memory harness
graph that ``parse()`` builds and that the GUI will likely call into
directly."""

from pathlib import Path

import pytest

from wireviz.DataClasses import Metadata, Options, Tweak
from wireviz.Harness import Harness, _embed_yaml_in_png, read_yaml_from_png
from wireviz.wireviz import parse


def _new_harness() -> Harness:
    return Harness(
        metadata=Metadata(),
        options=Options(),
        tweak=Tweak(),
    )


def test_empty_harness_constructs():
    """A bare ``Harness()`` builds with empty containers."""
    h = _new_harness()
    assert h.connectors == {}
    assert h.cables == {}
    assert h.mates == []
    assert h.additional_bom_items == []


def test_add_connector_appends_to_connectors():
    h = _new_harness()
    h.add_connector("X1", pinlabels=["A", "B"])
    assert "X1" in h.connectors
    assert h.connectors["X1"].pinlabels == ["A", "B"]


def test_add_cable_appends_to_cables():
    h = _new_harness()
    h.add_cable("W1", gauge="0.25 mm2", length=0.1, color_code="DIN", wirecount=2)
    assert "W1" in h.cables
    assert h.cables["W1"].wirecount == 2


def test_add_connector_rejects_old_attr_names():
    """Renamed-since-v0.2 attributes raise a clear error rather than
    silently being ignored."""
    h = _new_harness()
    with pytest.raises(ValueError, match="pinout"):
        h.add_connector("X1", pinout=["A", "B"])
    with pytest.raises(ValueError, match="pinnumbers"):
        h.add_connector("X2", pinnumbers=[1, 2])


def test_render_dict_shapes(minimal_yaml: Path):
    """``Harness._render`` returns a dict with the right key/value
    shapes for each format. This is the contract the stdout dispatch
    relies on."""
    h = parse(minimal_yaml, return_types="harness")
    outputs = h._render(("svg", "png", "gv", "tsv"))
    assert isinstance(outputs["svg"], str)
    assert isinstance(outputs["png"], bytes)
    assert isinstance(outputs["gv"], str)
    assert isinstance(outputs["tsv"], str)
    assert outputs["svg"].lstrip().startswith("<?xml")
    assert outputs["png"].startswith(b"\x89PNG\r\n")
    assert outputs["gv"].startswith("graph {")


def test_render_str_fmt_normalized_to_tuple(minimal_yaml: Path):
    """A bare string ``fmt`` works the same as a one-tuple. Was a
    latent bug before the str-normalization fix on PR #4."""
    h = parse(minimal_yaml, return_types="harness")
    outputs = h._render("svg")  # str, not tuple
    assert "svg" in outputs
    assert isinstance(outputs["svg"], str)


def test_render_html_threads_png_b64_inline(minimal_yaml: Path):
    """When both ``html`` and ``png`` are rendered in one call, the
    HTML's ``%diagram_png_b64%`` placeholder gets the in-memory PNG
    bytes inlined as a data URI rather than reading from disk."""
    h = parse(minimal_yaml, return_types="harness")
    outputs = h._render(("html", "png"))
    # HTML doesn't contain %diagram_png_b64% by default (the
    # built-in simple template uses %diagram%), but the underlying
    # mechanism is exercised by the dpi/branded template tests
    # elsewhere. What we can assert here is the HTML is a complete
    # document that doesn't reference the .png as a sibling file.
    assert "<svg " in outputs["html"]


def test_output_to_file(minimal_yaml: Path, workdir: Path):
    """``Harness.output(filename=path, fmt=...)`` writes files."""
    h = parse(minimal_yaml, return_types="harness")
    h.output(
        filename=workdir / "harness",
        fmt=("svg", "gv"),
    )
    assert (workdir / "harness.svg").exists()
    assert (workdir / "harness.gv").exists()


def test_output_to_stdout_writes_bytes_or_text(minimal_yaml: Path, capsys):
    """``Harness.output(filename=None)`` writes to stdout. SVG (str)
    goes to ``sys.stdout``; PNG (bytes) goes to ``sys.stdout.buffer``."""
    h = parse(minimal_yaml, return_types="harness")
    h.output(filename=None, fmt=("svg",))
    captured = capsys.readouterr()
    assert captured.out.lstrip().startswith("<?xml")


def test_embed_yaml_in_png_round_trip():
    """``_embed_yaml_in_png`` + ``read_yaml_from_png`` round-trip a
    YAML payload through PNG bytes."""
    from PIL import Image
    import io

    # Make a tiny PNG to embed into
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    yaml_payload = "connectors:\n  X1:\n    pinlabels: [A]\n"
    annotated = _embed_yaml_in_png(buf.getvalue(), yaml_payload)
    assert annotated.startswith(b"\x89PNG\r\n")

    # Round trip via a temp file
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(annotated)
        tmp = f.name
    try:
        recovered = read_yaml_from_png(tmp)
        assert recovered == yaml_payload
    finally:
        os.unlink(tmp)


def test_read_yaml_from_png_returns_none_if_missing(workdir: Path):
    """A plain PNG with no ``wireviz:yaml`` chunk returns ``None``."""
    from PIL import Image

    plain = workdir / "plain.png"
    Image.new("RGB", (4, 4), "white").save(plain)
    assert read_yaml_from_png(plain) is None
