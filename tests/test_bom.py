# -*- coding: utf-8 -*-
"""Coverage of BOM aggregation logic."""

from pathlib import Path

import pytest

from wireviz.wireviz import parse


def _parse_to_tsv(yaml_str: str, workdir: Path, name: str = "bom") -> str:
    parse(
        yaml_str,
        output_formats=("tsv",),
        output_dir=workdir,
        output_name=name,
    )
    return (workdir / f"{name}.bom.tsv").read_text()


def test_bom_lists_connector(workdir: Path):
    tsv = _parse_to_tsv(
        """
connectors:
  X1:
    type: D-Sub
    pinlabels: [A, B]
cables:
  W1:
    gauge: 0.25 mm2
    length: 0.1
    color_code: DIN
    wirecount: 2
connections:
  - [{X1: [1, 2]}, {W1: [1, 2]}]
""",
        workdir,
    )
    assert "Connector" in tsv
    assert "X1" in tsv
    assert "D-Sub" in tsv


def test_bom_lists_cable_with_gauge_and_length(workdir: Path):
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {pinlabels: [A]}
cables:
  W1:
    gauge: 0.5 mm2
    length: 1.5
    color_code: DIN
    wirecount: 1
connections:
  - [{X1: [1]}, {W1: [1]}]
""",
        workdir,
    )
    assert "0.5" in tsv  # gauge token preserved
    assert "1.5" in tsv  # length appears
    assert "W1" in tsv


def test_bom_aggregates_identical_components(workdir: Path):
    """Two identical D-Sub connectors aggregate into one BOM row with
    qty=2 and both designators listed."""
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {type: D-Sub, pinlabels: [A]}
  X2: {type: D-Sub, pinlabels: [A]}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}, {X2: [1]}]
""",
        workdir,
    )
    rows = tsv.splitlines()
    dsub_rows = [r for r in rows[1:] if "D-Sub" in r]
    assert len(dsub_rows) == 1, "identical connectors should aggregate to one row"
    # Both designators should appear in the same row
    assert "X1" in dsub_rows[0] and "X2" in dsub_rows[0]


def test_bom_separates_connectors_with_different_types(workdir: Path):
    """A D-Sub and a Molex don't aggregate; they're different components."""
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {type: D-Sub, pinlabels: [A]}
  X2: {type: Molex KK, pinlabels: [A]}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}, {X2: [1]}]
""",
        workdir,
    )
    assert "D-Sub" in tsv and "Molex" in tsv
    rows = tsv.splitlines()
    assert len([r for r in rows[1:] if "D-Sub" in r]) == 1
    assert len([r for r in rows[1:] if "Molex" in r]) == 1


def test_bom_includes_additional_bom_items(workdir: Path):
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {pinlabels: [A]}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
additional_bom_items:
  - description: Heat shrink tubing 3mm
    qty: 4
    unit: cm
  - description: Cable tie
    qty: 6
""",
        workdir,
    )
    assert "Heat shrink tubing 3mm" in tsv
    assert "Cable tie" in tsv


def test_bom_ignores_components_marked_ignore_in_bom(workdir: Path):
    """``ignore_in_bom: true`` keeps a connector out of the BOM but
    still in the diagram."""
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {type: TestPin, pinlabels: [A], ignore_in_bom: true}
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
""",
        workdir,
    )
    assert "TestPin" not in tsv


def test_bom_part_numbers_appear(workdir: Path):
    """``pn``, ``mpn``, ``spn`` fields land in the BOM."""
    tsv = _parse_to_tsv(
        """
connectors:
  X1:
    type: D-Sub
    pinlabels: [A]
    pn: INTERNAL-001
    mpn: AMP-12345
    manufacturer: Amphenol
cables:
  W1: {gauge: 0.25 mm2, length: 0.1, color_code: DIN, wirecount: 1}
connections:
  - [{X1: [1]}, {W1: [1]}]
""",
        workdir,
    )
    assert "INTERNAL-001" in tsv
    assert "AMP-12345" in tsv
    assert "Amphenol" in tsv


def test_bom_bundle_category_emits_one_row_per_wire(workdir: Path):
    """A cable with ``category: bundle`` produces one BOM row per
    wire instead of a single cable row."""
    tsv = _parse_to_tsv(
        """
connectors:
  X1: {pinlabels: [A, B]}
cables:
  W1:
    category: bundle
    gauge: 0.25 mm2
    length: 0.1
    color_code: DIN
    wirecount: 2
connections:
  - [{X1: [1, 2]}, {W1: [1, 2]}]
""",
        workdir,
    )
    rows = tsv.splitlines()
    wire_rows = [r for r in rows[1:] if "Wire" in r]
    assert len(wire_rows) == 2, "bundle should emit one row per wire"
