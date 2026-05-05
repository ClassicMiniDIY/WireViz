# -*- coding: utf-8 -*-
"""CLI behavior tests via Click's ``CliRunner``.

Every flag, every error path, every input mode (file / stdin / .png).
The CLI is the user-visible surface — if anything regresses here,
people notice.
"""

from pathlib import Path

import pytest

from wireviz.Harness import read_yaml_from_png
from wireviz.wv_cli import wireviz as cli


# Tests in this file use the ``cli_runner`` fixture from conftest.py
# rather than instantiating CliRunner directly, so the Click 8.0-8.2
# vs 8.3+ ``mix_stderr`` API drift is handled in one place.


# --- Basic file-mode invocations --------------------------------------------


def test_cli_file_input_default_formats(runner, minimal_yaml: Path, workdir: Path):
    """No flags → defaults render html/png/svg/tsv next to the input."""
    target = workdir / "h.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, [str(target)])
    assert result.exit_code == 0, result.stderr
    for ext in ("html", "png", "svg", "bom.tsv"):
        assert (workdir / f"h.{ext}").exists(), f"{ext} missing"


def test_cli_format_flag_subset(runner, minimal_yaml: Path, workdir: Path):
    """``-f s`` only renders SVG."""
    target = workdir / "s.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, ["-f", "s", str(target)])
    assert result.exit_code == 0
    assert (workdir / "s.svg").exists()
    assert not (workdir / "s.png").exists()
    assert not (workdir / "s.html").exists()


def test_cli_pdf_format_flag(runner, minimal_yaml: Path, workdir: Path):
    """``-f P`` (capital P, distinct from lowercase p for PNG) produces PDF."""
    target = workdir / "p.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, ["-f", "P", str(target)])
    assert result.exit_code == 0
    pdf = workdir / "p.pdf"
    assert pdf.exists()
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_cli_unknown_format_uses_click_usage_error(runner, minimal_yaml: Path):
    """An unknown format flag raises ``click.UsageError`` → exit 2 plus
    the canonical 'Try \\'wireviz -h\\' for help.' footer."""
    result = runner.invoke(cli, ["-f", "X", str(minimal_yaml)])
    assert result.exit_code == 2
    assert "Unknown output format" in result.stderr
    assert "Try 'wireviz -h' for help" in result.stderr


def test_cli_missing_input_file_errors(runner, workdir: Path):
    """A non-existent input file produces a clean error."""
    result = runner.invoke(cli, [str(workdir / "does-not-exist.yml")])
    assert result.exit_code != 0
    assert "does not exist" in result.stderr.lower()


# --- output-dir / output-name -----------------------------------------------


def test_cli_output_dir(runner, minimal_yaml: Path, tmp_path: Path):
    """``-o`` redirects output to a different directory."""
    out = tmp_path / "out"
    out.mkdir()
    result = runner.invoke(
        cli, ["-f", "s", "-o", str(out), str(minimal_yaml)]
    )
    assert result.exit_code == 0
    assert (out / f"{minimal_yaml.stem}.svg").exists()


def test_cli_output_name(runner, minimal_yaml: Path, workdir: Path):
    """``-O`` overrides the output filename stem."""
    target = workdir / "input.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, ["-f", "s", "-O", "renamed", str(target)])
    assert result.exit_code == 0
    assert (workdir / "renamed.svg").exists()
    assert not (workdir / "input.svg").exists()


# --- stdin / stdout ----------------------------------------------------------


def test_cli_stdin_input(runner, minimal_yaml: Path, workdir: Path):
    """``wireviz -`` reads YAML from stdin."""
    yaml_text = minimal_yaml.read_text()
    result = runner.invoke(
        cli,
        ["-f", "s", "-O", "stdin_out", "-o", str(workdir), "-"],
        input=yaml_text,
    )
    assert result.exit_code == 0, result.stderr
    assert (workdir / "stdin_out.svg").exists()


def test_cli_stdout_svg(runner, minimal_yaml: Path):
    """``-O -`` (or ``-o -``) writes the single requested format to stdout."""
    result = runner.invoke(
        cli,
        ["-f", "s", "-O", "-", str(minimal_yaml)],
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.lstrip().startswith("<?xml")


def test_cli_stdout_multi_format_rejected(runner, minimal_yaml: Path):
    """Asking for multiple formats with stdout output is a usage error."""
    result = runner.invoke(
        cli,
        ["-f", "shp", "-O", "-", str(minimal_yaml)],
    )
    assert result.exit_code == 2
    assert "Exactly one output format" in result.stderr


# --- prepend file -----------------------------------------------------------


def test_cli_prepend_file(runner, workdir: Path):
    """``-p`` concatenates a prepend YAML before the main input —
    typical use is sharing connector/cable libraries."""
    library = workdir / "lib.yml"
    library.write_text(
        "connectors:\n"
        "  STDPIN:\n"
        "    pinlabels: [A, B, C]\n"
    )
    main = workdir / "main.yml"
    main.write_text(
        "cables:\n"
        "  W1:\n"
        "    gauge: 0.25 mm2\n"
        "    length: 0.1\n"
        "    color_code: DIN\n"
        "    wirecount: 3\n"
        "connections:\n"
        "  - [{STDPIN: [1, 2, 3]}, {W1: [1, 2, 3]}]\n"
    )
    result = runner.invoke(
        cli, ["-f", "g", "-p", str(library), str(main)]
    )
    assert result.exit_code == 0, result.stderr
    gv = (workdir / "main.gv").read_text()
    assert "STDPIN" in gv


# --- --no-embed-yaml --------------------------------------------------------


def test_cli_default_embeds_yaml_in_png(
    runner, minimal_yaml: Path, workdir: Path
):
    """The default CLI behavior embeds the source YAML in PNG output."""
    target = workdir / "embed.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, ["-f", "p", str(target)])
    assert result.exit_code == 0
    extracted = read_yaml_from_png(workdir / "embed.png")
    assert extracted is not None
    assert "X1" in extracted


def test_cli_no_embed_yaml_flag(runner, minimal_yaml: Path, workdir: Path):
    """``--no-embed-yaml`` opts out of the chunk."""
    target = workdir / "plain.yml"
    target.write_text(minimal_yaml.read_text())
    result = runner.invoke(cli, ["-f", "p", "--no-embed-yaml", str(target)])
    assert result.exit_code == 0
    assert read_yaml_from_png(workdir / "plain.png") is None


# --- .png input / round-trip ------------------------------------------------


def test_cli_png_input_extracts_yaml(
    runner, minimal_yaml: Path, workdir: Path
):
    """A .png input is auto-detected; the embedded YAML is extracted
    and re-rendered."""
    target = workdir / "round.yml"
    target.write_text(minimal_yaml.read_text())
    runner.invoke(cli, ["-f", "p", str(target)])
    # Now feed the PNG back in
    result = runner.invoke(
        cli, ["-f", "s", "-O", "from_png", str(workdir / "round.png")]
    )
    assert result.exit_code == 0, result.stderr
    assert (workdir / "from_png.svg").exists()
    assert "(extracted YAML)" in result.stderr


def test_cli_png_input_without_chunk_errors(runner, workdir: Path, tmp_path: Path):
    """A PNG without the ``wireviz:yaml`` chunk produces a clean
    UsageError, not a stack trace."""
    from PIL import Image

    plain = workdir / "plain.png"
    Image.new("RGB", (8, 8), "white").save(plain)
    result = runner.invoke(cli, ["-f", "s", str(plain)])
    assert result.exit_code == 2
    assert "no embedded WireViz YAML" in result.stderr


def test_cli_png_input_corrupt_errors_cleanly(runner, workdir: Path):
    """A file whose .png suffix lies (not actually a PNG) produces a
    clean error from the PIL guard."""
    fake = workdir / "fake.png"
    fake.write_text("definitely not a PNG")
    result = runner.invoke(cli, ["-f", "s", str(fake)])
    assert result.exit_code == 2
    assert "Could not read PNG" in result.stderr


# --- --template-dir ---------------------------------------------------------


def test_cli_template_dir(
    runner,
    custom_template_yaml: Path,
    custom_template_dir: Path,
    workdir: Path,
):
    """``-t`` searches the named directory for the template before
    falling back to source-dir / output-dir / built-ins."""
    yaml_target = workdir / "custom.yml"
    yaml_target.write_text(custom_template_yaml.read_text())
    result = runner.invoke(
        cli,
        ["-f", "h", "-t", str(custom_template_dir), str(yaml_target)],
    )
    assert result.exit_code == 0, result.stderr
    html = (workdir / "custom.html").read_text()
    assert "CMDIY HARNESS" in html, "branded template was not loaded"


def test_cli_template_not_found(runner, custom_template_yaml: Path, workdir: Path):
    """A custom template referenced but not found anywhere errors clearly."""
    yaml_target = workdir / "missing.yml"
    yaml_target.write_text(custom_template_yaml.read_text())
    result = runner.invoke(cli, ["-f", "h", str(yaml_target)])
    assert result.exit_code != 0


# --- version flag -----------------------------------------------------------


def test_cli_version_flag_writes_to_stderr(runner):
    """``-V`` prints the version banner. The banner currently goes to
    stderr along with all other status messages so stdout stays clean
    for piping."""
    result = runner.invoke(cli, ["-V"])
    assert result.exit_code == 0
    assert "WireViz" in result.stderr
