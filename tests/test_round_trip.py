# -*- coding: utf-8 -*-
"""Round-trip tests — render → output bytes → re-parse → identical
result. The high-leverage scenarios are PNG-with-embedded-YAML and
the stdin/stdout pipe."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from wireviz.Harness import read_yaml_from_png
from wireviz.wireviz import parse
from wireviz.wv_cli import wireviz as cli


def test_png_yaml_round_trip_via_cli(workdir: Path, minimal_yaml: Path):
    """Render YAML → PNG-with-embedded-source → feed PNG back to CLI →
    rendered output uses the same harness model. This is the
    load-bearing workflow for the planned wireviz-gui."""
    runner = CliRunner()

    target = workdir / "orig.yml"
    target.write_text(minimal_yaml.read_text())

    # First render: produces orig.png with embedded YAML
    result = runner.invoke(cli, ["-f", "p", str(target)])
    assert result.exit_code == 0, result.stderr

    # Second render: feed orig.png back, produce a fresh SVG
    result2 = runner.invoke(
        cli, ["-f", "s", "-O", "round2", str(workdir / "orig.png")]
    )
    assert result2.exit_code == 0, result2.stderr
    assert "(extracted YAML)" in result2.stderr

    # The re-rendered SVG should be a valid SVG referencing X1 and W1
    svg = (workdir / "round2.svg").read_text()
    assert "<?xml" in svg
    assert "X1" in svg
    assert "W1" in svg


def test_png_yaml_round_trip_byte_identical_yaml(
    workdir: Path, minimal_yaml: Path
):
    """The YAML extracted from a PNG matches the YAML that went in
    byte-for-byte (no whitespace normalization, no comment stripping)."""
    yaml_text = minimal_yaml.read_text()
    parse(
        yaml_text,
        output_formats=("png",),
        output_dir=workdir,
        output_name="bytes",
    )
    extracted = read_yaml_from_png(workdir / "bytes.png")
    assert extracted == yaml_text


def test_stdin_to_stdout_svg_roundtrip(minimal_yaml: Path):
    """``cat harness.yml | wireviz -f s -O - -`` produces a valid SVG
    on stdout."""
    runner = CliRunner()
    yaml_text = minimal_yaml.read_text()
    result = runner.invoke(
        cli,
        ["-f", "s", "-O", "-", "-"],
        input=yaml_text,
    )
    assert result.exit_code == 0
    assert result.stdout.lstrip().startswith("<?xml")
    assert "X1" in result.stdout


def test_stdin_to_stdout_png_roundtrip(minimal_yaml: Path):
    """Same pipeline but binary PNG output."""
    runner = CliRunner()
    yaml_text = minimal_yaml.read_text()
    result = runner.invoke(
        cli,
        ["-f", "p", "-O", "-", "-"],
        input=yaml_text,
    )
    assert result.exit_code == 0
    out = (
        result.stdout_bytes
        if hasattr(result, "stdout_bytes")
        else result.stdout.encode("latin-1")
    )
    assert out.startswith(b"\x89PNG\r\n")


def test_dict_input_round_trip_via_yaml_dump(workdir: Path, minimal_yaml: Path):
    """Pre-parsed dict input gets ``yaml.safe_dump``'d back when
    embedded into PNG, so round-trip is still possible (via re-parse
    of the dumped form)."""
    import yaml as yaml_mod

    data = yaml_mod.safe_load(minimal_yaml.read_text())
    expected = yaml_mod.safe_load(minimal_yaml.read_text())  # second copy
    parse(
        data,
        output_formats=("png",),
        output_dir=workdir,
        output_name="dict_in",
    )
    extracted = read_yaml_from_png(workdir / "dict_in.png")
    assert extracted is not None
    # Re-parsing the extracted YAML should yield the same shape as the
    # original input (compared against a fresh load to avoid being
    # confused by any in-place mutation of `data`).
    re_parsed = yaml_mod.safe_load(extracted)
    assert re_parsed == expected


def test_dict_input_not_mutated(minimal_yaml: Path):
    """parse() must not mutate dict inputs — programmatic callers
    keep references to their YAML model and expect it to survive
    rendering unchanged.

    Pre-fix, the in-place expansion of the connections section
    (turning ``[[{X1: [1,2]}, {W1: [1,2]}]]`` into
    ``[[{X1: 1}, {X1: 2}], [{W1: 1}, {W1: 2}]]``) leaked back to
    the caller's dict.
    """
    import copy
    import yaml as yaml_mod

    data = yaml_mod.safe_load(minimal_yaml.read_text())
    snapshot = copy.deepcopy(data)
    parse(data, return_types="harness")
    assert data == snapshot, "parse() mutated the caller's dict"
