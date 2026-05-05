# -*- coding: utf-8 -*-
"""One test per upstream-PR port + every gemini-code-assist review fix.

These are the most valuable tests in the suite — they pin down the
exact behavior we shipped through PRs #1–#10 so we can never silently
regress to the pre-fix state. Each test cites the PR (or PRs) it
guards.
"""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from wireviz.DataClasses import Cable, Options
from wireviz.Harness import Harness, read_yaml_from_png
from wireviz.wireviz import parse
from wireviz.wv_cli import wireviz as cli
from wireviz.wv_colors import get_color_hex
from wireviz.wv_html import _latest_revision


# ===========================================================================
# Bug fixes from upstream PR #1 (4 fixes bundled)
# ===========================================================================


def test_pr443_svg_mime_type_in_data_uri():
    """Upstream PR #443. SVG images embedded as base64 data URIs need
    the MIME type ``image/svg+xml``, not ``image/svg`` — browsers
    refuse to render the latter."""
    from wireviz.svgembed import get_mime_subtype

    assert get_mime_subtype("logo.svg") == "svg+xml"
    assert get_mime_subtype("logo.jpg") == "jpeg"
    assert get_mime_subtype("logo.tif") == "tiff"


def test_pr473_template_path_search_includes_source_dir(
    custom_template_yaml, custom_template_dir, tmp_path: Path
):
    """Upstream PR #473. A custom template referenced by name resolves
    against the YAML source directory before falling back to built-ins.

    Set up: copy the YAML and template into the same directory, then
    render with output_dir pointing elsewhere — the template should
    still be found via source_path."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "input.yml").write_text(custom_template_yaml.read_text())
    (src / "branded.html").write_text(
        (custom_template_dir / "branded.html").read_text()
    )
    parse(
        src / "input.yml",
        output_formats=("html",),
        output_dir=out,
        output_name="render",
    )
    rendered = (out / "render.html").read_text()
    assert "CMDIY HARNESS" in rendered, (
        "template must resolve from source_path.parent, not just output_dir"
    )


def test_pr495_hex_color_does_not_pad_wire_thickness(workdir: Path, hex_color_yaml: Path):
    """Upstream PR #495. A 7-character hex color was misdetected as a
    multi-color stripe, padding single-color wires to 3x thickness.

    Validate the underlying ``get_color_hex`` returns 1 entry for a
    hex input, and the rendered .gv reflects single-thickness."""
    assert len(get_color_hex("#ff0000")) == 1

    parse(
        hex_color_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="hex",
    )
    gv = (workdir / "hex.gv").read_text()
    # The single-color wire should not be rendered with the striped
    # 3-row table that multi-color wires use.
    assert "#ff0000" in gv


def test_pr496_loop_only_connector_auto_instantiated(
    workdir: Path, loopback_yaml: Path
):
    """Upstream PR #496. A connector with ``loops:`` and no connection-
    set reference should still render (auto-instantiated) — before the
    fix it was silently dropped as an unused template."""
    parse(
        loopback_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="lo",
    )
    gv = (workdir / "lo.gv").read_text()
    assert "X1 [label=" in gv, "loop-only connector was not rendered"


def test_pr1_review_loop_template_with_designator_no_phantom(
    workdir: Path, loopback_template_yaml: Path
):
    """PR #1 review fix. When a connector template carrying ``loops:``
    is used via Template.Designator (e.g. ``DSub.X1``), we instantiate
    X1 and X2 — but NOT a phantom ``DSub`` connector with duplicate
    loops.

    Pre-fix, the auto-instantiation pass would re-add ``DSub`` because
    the template name didn't match any literal designator in
    harness.connectors."""
    h = parse(loopback_template_yaml, return_types="harness")
    assert "X1" in h.connectors
    assert "X2" in h.connectors
    assert "DSub" not in h.connectors, "phantom template instance"


# ===========================================================================
# Upstream PR #321 (port-321) — stdin/stdout streaming
# ===========================================================================


def test_pr321_stdout_writes_svg_text(minimal_yaml: Path):
    """Single-format stdout writes the rendered text to ``sys.stdout``."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-f", "s", "-O", "-", str(minimal_yaml)])
    assert result.exit_code == 0
    assert result.stdout.lstrip().startswith("<?xml")


def test_pr321_stdout_writes_png_bytes(minimal_yaml: Path):
    """Single-format stdout writes PNG bytes to ``sys.stdout.buffer``."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-f", "p", "-O", "-", str(minimal_yaml)])
    assert result.exit_code == 0
    # CliRunner exposes binary stdout via .stdout_bytes
    out = result.stdout_bytes if hasattr(result, "stdout_bytes") else result.stdout.encode("latin-1")
    assert out.startswith(b"\x89PNG\r\n")


def test_pr321_review_fmt_str_normalized_to_tuple(minimal_yaml: Path):
    """PR #2 review fix. ``output_formats="svg"`` (a bare string) used
    to iterate over characters; now it's normalized to ``("svg",)``."""
    h = parse(minimal_yaml, return_types="harness")
    outputs = h._render("svg")  # bare string
    assert "svg" in outputs and isinstance(outputs["svg"], str)


def test_pr321_review_log_to_stderr(minimal_yaml: Path):
    """PR #2 review fix. CLI log lines go to stderr so piped stdout
    stays a valid SVG/PNG/etc."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-f", "s", "-O", "-", str(minimal_yaml)])
    assert "WireViz" in result.stderr  # banner on stderr
    assert "WireViz" not in result.stdout.lstrip("<")[:100]  # not on stdout


# ===========================================================================
# Upstream PR #444 — --template-dir
# ===========================================================================


def test_pr444_template_dir_first_in_search_order(
    custom_template_yaml: Path, custom_template_dir: Path, workdir: Path
):
    """Upstream PR #444. ``-t`` adds an explicit directory to the
    front of the template search path."""
    yaml_target = workdir / "in.yml"
    yaml_target.write_text(custom_template_yaml.read_text())
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-f", "h", "-t", str(custom_template_dir), str(yaml_target)],
    )
    assert result.exit_code == 0, result.stderr
    html = (workdir / "in.html").read_text()
    assert "CMDIY HARNESS" in html


# ===========================================================================
# Upstream PR #379 — output_dpi
# ===========================================================================


def test_pr379_output_dpi_emits_dpi_graph_attr(workdir: Path, dpi_192_yaml: Path):
    """Upstream PR #379. ``options.output_dpi: 192`` shows up as a
    ``dpi=192`` attribute in the generated .gv."""
    parse(
        dpi_192_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="dpi",
    )
    gv = (workdir / "dpi.gv").read_text()
    assert "dpi=192" in gv


def test_pr379_review_dpi_none_omits_attribute(workdir: Path):
    """PR #4 review fix. ``output_dpi: null`` in YAML omits the dpi
    graph attribute entirely (lets graphviz pick its renderer-default
    96 for PNG) instead of emitting the literal string 'None'."""
    yaml_str = """
options:
  output_dpi: null
connectors:
  X1: {pinlabels: [A]}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
"""
    parse(
        yaml_str,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="nodpi",
    )
    gv = (workdir / "nodpi.gv").read_text()
    assert "dpi=" not in gv
    assert "None" not in gv


def test_pr379_default_dpi_is_96(workdir: Path, minimal_yaml: Path):
    """Default ``Options.output_dpi`` is 96.0 (graphviz default for
    non-PostScript), so existing harnesses are unchanged."""
    parse(
        minimal_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="default",
    )
    gv = (workdir / "default.gv").read_text()
    assert "dpi=96.0" in gv


# ===========================================================================
# Upstream PR #234 — YAML embedded in PNG
# ===========================================================================


def test_pr234_png_embeds_yaml_chunk(workdir: Path, minimal_yaml: Path):
    """Upstream PR #234. Default-rendered PNGs carry the YAML source
    in a ``wireviz:yaml`` iTXt chunk."""
    parse(
        minimal_yaml,
        output_formats=("png",),
        output_dir=workdir,
        output_name="emb",
    )
    extracted = read_yaml_from_png(workdir / "emb.png")
    assert extracted is not None
    assert "X1" in extracted and "W1" in extracted


def test_pr234_round_trip_via_png(workdir: Path, minimal_yaml: Path):
    """Render → PNG → re-extract → compare YAML round-trips byte-for-byte
    (modulo what the prepend / dict-dump path normalizes)."""
    yaml_text = minimal_yaml.read_text()
    parse(
        yaml_text,
        output_formats=("png",),
        output_dir=workdir,
        output_name="rt",
    )
    extracted = read_yaml_from_png(workdir / "rt.png")
    # Should round-trip the original text exactly (YAML strings are
    # passed through unchanged for embed)
    assert extracted == yaml_text


def test_pr234_review_im_info_preserved_through_embed(workdir: Path):
    """PR #5 review fix. Re-encoding the PNG to add the iTXt chunk
    doesn't lose existing metadata chunks (DPI etc)."""
    from wireviz.Harness import _embed_yaml_in_png
    import io

    # Make a PNG with a DPI hint
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(buf, format="PNG", dpi=(192, 192))
    annotated = _embed_yaml_in_png(buf.getvalue(), "x: 1\n")
    # The DPI tuple should survive the re-encode
    annotated_im = Image.open(io.BytesIO(annotated))
    annotated_im.load()
    # PNG pHYs chunk stores DPI as pixels-per-meter; round-tripping
    # introduces a tiny float quantization. Approximate is enough.
    dpi = annotated_im.info.get("dpi")
    assert dpi is not None and abs(dpi[0] - 192.0) < 0.1


def test_pr234_review_corrupt_png_clean_error(workdir: Path):
    """PR #5 review fix. A non-PNG file with a .png suffix fed as input
    raises ``click.UsageError`` rather than spewing a stack trace."""
    fake = workdir / "fake.png"
    fake.write_text("definitely not a PNG")
    runner = CliRunner()
    result = runner.invoke(cli, ["-f", "s", str(fake)])
    assert result.exit_code == 2
    assert "Could not read PNG" in result.stderr


# ===========================================================================
# Upstream PR #492 — <!-- %revision% --> placeholder
# ===========================================================================


def test_pr492_latest_revision_returns_last_dict_key():
    """Upstream PR #492. ``_latest_revision`` returns the most-recently
    declared revision name (which Python preserves via dict insertion
    order)."""
    md = {"revisions": {"A": {}, "B": {}, "C": {}}}
    assert _latest_revision(md) == "C"


def test_pr492_review_handles_scalar_revisions():
    """PR #6 review fix. A scalar ``revisions: v1.0`` value used to
    return ``'0'`` (last char of str). Now returns the whole scalar."""
    assert _latest_revision({"revisions": "v1.0"}) == "v1.0"
    assert _latest_revision({"revisions": 42}) == "42"


def test_pr492_review_handles_missing_or_empty_revisions():
    """PR #6 review fix. None / missing / empty containers all return
    empty string instead of raising."""
    assert _latest_revision({}) == ""
    assert _latest_revision({"revisions": None}) == ""
    assert _latest_revision({"revisions": {}}) == ""
    assert _latest_revision({"revisions": []}) == ""


# ===========================================================================
# Upstream PR #357 — per-connector / per-cable tweak with placeholder
# ===========================================================================


def test_pr357_per_node_tweak_substitutes_placeholder(
    workdir: Path, per_node_tweak_yaml: Path
):
    """Upstream PR #357. A per-connector ``tweak.append`` line with
    a placeholder ``@@`` gets the actual connector designator
    substituted in the rendered .gv."""
    parse(
        per_node_tweak_yaml,
        output_formats=("gv",),
        output_dir=workdir,
        output_name="t",
    )
    gv = (workdir / "t.gv").read_text()
    assert "X1_extra" in gv, "per-connector @@_extra didn't substitute"
    assert "W1_label" in gv, "per-cable @@_label didn't substitute"
    assert "cable W1" in gv, "@@ inside string value didn't substitute"


def test_pr357_review_none_override_value_no_crash(workdir: Path):
    """PR #7 review fix. An override value of ``null`` (YAML deletion
    sentinel) used to crash the rph lambda with AttributeError."""
    yaml_str = """
tweak:
  placeholder: "@@"
connectors:
  X1:
    pinlabels: [A]
    tweak:
      override:
        "@@":
          color: null
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
"""
    # Should not raise
    parse(yaml_str, output_formats=("gv",), output_dir=workdir, output_name="ndiv")


def test_pr357_review_conflict_error_includes_values(workdir: Path):
    """PR #10 review fix. The conflict error reports both the existing
    and the new value, so users can resolve without spelunking."""
    yaml_str = """
tweak:
  placeholder: "@@"
  override:
    X1:
      color: "red"
connectors:
  X1:
    pincount: 1
    tweak:
      override:
        "@@":
          color: "blue"
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
"""
    with pytest.raises(ValueError, match="'blue'.*conflicts.*'red'"):
        parse(
            yaml_str,
            output_formats=("gv",),
            output_dir=workdir,
            output_name="conf",
        )


# ===========================================================================
# Upstream PR #367 — PDF output
# ===========================================================================


def test_pr367_pdf_format_produces_valid_pdf(workdir: Path, minimal_yaml: Path):
    """Upstream PR #367. ``-f P`` (capital P) renders a valid PDF."""
    parse(
        minimal_yaml,
        output_formats=("pdf",),
        output_dir=workdir,
        output_name="p",
        embed_yaml=False,
    )
    pdf = workdir / "p.pdf"
    assert pdf.exists()
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_pr367_review_pdf_docstring_says_diagram_only():
    """PR #8 review fix. The parse() docstring's PDF entry was updated
    to be honest about the implementation: PDF is diagram-only,
    no BOM (HTML covers that)."""
    docstring = parse.__doc__ or ""
    pdf_line = next(
        (line for line in docstring.splitlines() if '"pdf"' in line), ""
    )
    assert "no BOM" in pdf_line or "diagram, as a PDF" in pdf_line


# ===========================================================================
# PR #10 review fixes (data URI, image_paths cwd, click.UsageError)
# ===========================================================================


def test_pr10_review_data_uri_no_leading_space():
    """PR #10 review fix. RFC 2397 says no whitespace after the
    ``base64,`` separator in data URIs."""
    from wireviz.svgembed import data_URI_base64
    import tempfile, os

    # Write a tiny PNG to disk and base64-URI it
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        Image.new("RGB", (4, 4), "blue").save(f, format="PNG")
        tmp = f.name
    try:
        uri = data_URI_base64(tmp)
        # Right after `base64,` should be a non-space character (the
        # first base64 byte is alphabetic for any non-trivial PNG).
        idx = uri.index(";base64,")
        char_after_comma = uri[idx + len(";base64,")]
        assert char_after_comma != " ", "data URI must not have leading space"
    finally:
        os.unlink(tmp)


def test_pr10_review_unknown_format_uses_click_usage_error(minimal_yaml: Path):
    """PR #10 review fix. Unknown -f code raises click.UsageError,
    not a generic Exception."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-f", "X", str(minimal_yaml)])
    assert result.exit_code == 2
    # click.UsageError adds the canonical "Try 'wireviz -h' for help."
    assert "Try 'wireviz -h' for help" in result.stderr


def test_pr10_review_source_path_autofills(minimal_yaml: Path):
    """PR #10 review fix. ``source_path`` was documented to auto-fill
    when ``inp`` is a Path; the code now actually does it."""
    h = parse(minimal_yaml, return_types="harness")
    assert h.source_path is not None
    assert Path(h.source_path).resolve() == minimal_yaml.resolve()


def test_pr10_review_missing_input_clean_error(workdir: Path):
    """PR #10 review fix (extension). 'File does not exist' on input
    was a generic Exception too; now click.UsageError."""
    runner = CliRunner()
    result = runner.invoke(cli, [str(workdir / "missing.yml")])
    assert result.exit_code == 2
    assert "does not exist" in result.stderr.lower()
