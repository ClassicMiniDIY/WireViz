# -*- coding: utf-8 -*-
"""Coverage of the public ``wireviz.parse()`` API surface — input
shapes, output shapes, and the various optional parameters.

Anything the GUI or other programmatic callers might lean on goes
here. The CLI lives in test_cli.py.
"""

from pathlib import Path

import pytest
import yaml

from wireviz.Harness import Harness
from wireviz.wireviz import parse


# --- Input shapes (Path / str / dict) ---------------------------------------


def test_parse_path_input(minimal_yaml: Path, workdir: Path):
    """``parse()`` accepts a Path-like for the YAML input."""
    parse(
        minimal_yaml,
        output_formats=("svg",),
        output_dir=workdir,
        output_name="p",
        embed_yaml=False,
    )
    assert (workdir / "p.svg").exists()


def test_parse_string_input(minimal_yaml: Path, workdir: Path):
    """``parse()`` accepts a YAML string for the YAML input."""
    yaml_str = minimal_yaml.read_text()
    parse(
        yaml_str,
        output_formats=("svg",),
        output_dir=workdir,
        output_name="s",
        embed_yaml=False,
    )
    assert (workdir / "s.svg").exists()


def test_parse_dict_input(minimal_yaml: Path, workdir: Path):
    """``parse()`` accepts a pre-parsed dict for the YAML input."""
    data = yaml.safe_load(minimal_yaml.read_text())
    parse(
        data,
        output_formats=("svg",),
        output_dir=workdir,
        output_name="d",
        embed_yaml=False,
    )
    assert (workdir / "d.svg").exists()


def test_parse_rejects_non_dict_yaml(workdir: Path):
    """A YAML string that doesn't decode to a dict at the top level
    raises TypeError rather than silently producing nothing."""
    with pytest.raises(TypeError, match="dict as top-level YAML"):
        parse(
            "- just\n- a\n- list\n",
            output_formats=("svg",),
            output_dir=workdir,
            output_name="bad",
        )


# --- output_formats variations ----------------------------------------------


def test_parse_output_formats_string(minimal_yaml: Path, workdir: Path):
    """A bare string ``output_formats="svg"`` is accepted; the underlying
    ``Harness.output()`` normalizes it to a one-tuple."""
    parse(
        minimal_yaml,
        output_formats="svg",
        output_dir=workdir,
        output_name="str",
        embed_yaml=False,
    )
    assert (workdir / "str.svg").exists()


def test_parse_output_formats_tuple(minimal_yaml: Path, workdir: Path):
    parse(
        minimal_yaml,
        output_formats=("svg", "png"),
        output_dir=workdir,
        output_name="t",
        embed_yaml=False,
    )
    assert (workdir / "t.svg").exists()
    assert (workdir / "t.png").exists()


def test_parse_output_formats_list(minimal_yaml: Path, workdir: Path):
    parse(
        minimal_yaml,
        output_formats=["svg", "png"],
        output_dir=workdir,
        output_name="l",
        embed_yaml=False,
    )
    assert (workdir / "l.svg").exists()
    assert (workdir / "l.png").exists()


def test_parse_no_outputs_or_returns_raises(minimal_yaml: Path):
    """Calling ``parse()`` with neither ``output_formats`` nor
    ``return_types`` is a usage error."""
    with pytest.raises(Exception, match="No output formats or return types"):
        parse(minimal_yaml)


# --- return_types ------------------------------------------------------------


def test_parse_returns_harness_object(minimal_yaml: Path):
    """``return_types="harness"`` yields a populated Harness instance."""
    h = parse(minimal_yaml, return_types="harness")
    assert isinstance(h, Harness)
    assert "X1" in h.connectors
    assert "W1" in h.cables


def test_parse_returns_svg_string(minimal_yaml: Path):
    """``return_types="svg"`` yields an SVG string."""
    svg = parse(minimal_yaml, return_types="svg")
    assert isinstance(svg, str)
    assert svg.lstrip().startswith("<?xml")


def test_parse_returns_png_bytes(minimal_yaml: Path):
    """``return_types="png"`` yields PNG bytes."""
    png = parse(minimal_yaml, return_types="png")
    assert isinstance(png, bytes)
    assert png.startswith(b"\x89PNG\r\n")


def test_parse_returns_tuple_for_multiple(minimal_yaml: Path):
    """Multiple return_types yields a tuple, not a single value."""
    result = parse(minimal_yaml, return_types=("svg", "harness"))
    assert isinstance(result, tuple) and len(result) == 2
    svg, h = result
    assert isinstance(svg, str)
    assert isinstance(h, Harness)


# --- source_path semantics ---------------------------------------------------


def test_source_path_autofills_from_path_input(minimal_yaml: Path):
    """When the input is a Path, source_path is auto-filled and visible
    on the returned Harness — the docstring promises this."""
    h = parse(minimal_yaml, return_types="harness")
    assert h.source_path is not None
    assert Path(h.source_path).resolve() == minimal_yaml.resolve()


def test_source_path_explicit_overrides_inp(minimal_yaml: Path, tmp_path: Path):
    """An explicit ``source_path`` kwarg is preserved verbatim and not
    silently overwritten by the auto-fill logic."""
    explicit = tmp_path / "stand-in.yml"
    h = parse(minimal_yaml, return_types="harness", source_path=explicit)
    assert h.source_path == explicit


def test_source_path_string_input_no_autofill():
    """When the input is a YAML string (no source path available),
    source_path stays None unless explicitly passed."""
    h = parse(
        "connectors:\n  X1:\n    pinlabels: [A]\n"
        "cables:\n  W1:\n    gauge: 0.25 mm2\n    length: 0.1\n"
        "    color_code: DIN\n    wirecount: 1\n"
        "connections:\n  - [{X1: [1]}, {W1: [1]}]\n",
        return_types="harness",
    )
    assert h.source_path is None


# --- output_dir / output_name conventions -----------------------------------


def test_output_dir_defaults_to_input_parent(minimal_yaml: Path, tmp_path: Path):
    """Without an explicit ``output_dir``, files are written next to
    the input YAML."""
    target = tmp_path / "harness.yml"
    target.write_text(minimal_yaml.read_text())
    parse(target, output_formats=("svg",), embed_yaml=False)
    assert (tmp_path / "harness.svg").exists()


def test_output_name_defaults_to_input_stem(minimal_yaml: Path, tmp_path: Path):
    """Without an explicit ``output_name``, the input file's stem is used."""
    target = tmp_path / "harness.yml"
    target.write_text(minimal_yaml.read_text())
    parse(target, output_formats=("svg",), embed_yaml=False)
    assert (tmp_path / "harness.svg").exists()


# --- embed_yaml flag --------------------------------------------------------


def test_embed_yaml_default_true(minimal_yaml: Path, workdir: Path):
    """By default, PNG output carries the embedded YAML chunk."""
    from wireviz.Harness import read_yaml_from_png

    parse(
        minimal_yaml,
        output_formats=("png",),
        output_dir=workdir,
        output_name="default",
    )
    extracted = read_yaml_from_png(workdir / "default.png")
    assert extracted is not None and "X1" in extracted


def test_embed_yaml_false_strips_chunk(minimal_yaml: Path, workdir: Path):
    """``embed_yaml=False`` produces a plain PNG with no source chunk."""
    from wireviz.Harness import read_yaml_from_png

    parse(
        minimal_yaml,
        output_formats=("png",),
        output_dir=workdir,
        output_name="plain",
        embed_yaml=False,
    )
    assert read_yaml_from_png(workdir / "plain.png") is None


# --- additional_bom_items section ------------------------------------------


def test_additional_bom_items_appear_in_tsv(workdir: Path):
    """Items in ``additional_bom_items:`` are aggregated into the BOM."""
    yaml_str = """
connectors:
  X1: {pinlabels: [A, B]}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 2}
connections:
  - [{X1: [1, 2]}, {W1: [1, 2]}]
additional_bom_items:
  - description: Heat shrink tubing
    qty: 4
    unit: cm
"""
    parse(
        yaml_str,
        output_formats=("tsv",),
        output_dir=workdir,
        output_name="extra",
    )
    tsv = (workdir / "extra.bom.tsv").read_text()
    assert "Heat shrink tubing" in tsv
