# -*- coding: utf-8 -*-
"""Coverage of color-code parsing, hex handling, and the wire-thickness
padding heuristic that PR #495 fixed.

WireViz supports several wire color schemes (DIN 47100, IEC 60757,
25-pair, TIA/EIA 568) plus user-defined colors and raw hex values."""

import pytest

from wireviz.wv_colors import (
    COLOR_CODES,
    get_color_hex,
    translate_color,
)


# --- Color schemes ----------------------------------------------------------


def test_din_color_scheme_first_wires():
    """DIN 47100 starts WH, BN, GN, YE, GY..."""
    din = COLOR_CODES["DIN"]
    assert din[0:5] == ["WH", "BN", "GN", "YE", "GY"]


def test_iec_color_scheme_first_wires():
    """IEC 60757 starts BN, RD, OG, YE, GN..."""
    iec = COLOR_CODES["IEC"]
    assert iec[0:5] == ["BN", "RD", "OG", "YE", "GN"]


def test_tia_eia_t568b_scheme_present():
    """T568B is the standard ethernet wiring sequence."""
    t568b = COLOR_CODES["T568B"]
    # Should be 8 wires (4 pairs)
    assert len(t568b) == 8


def test_telephone_25_pair_scheme_present():
    """The 25-pair telephone scheme ('TEL') has 50 entries (25 pairs,
    each direction)."""
    tel = COLOR_CODES["TEL"]
    assert len(tel) == 50


# --- Hex color parsing -----------------------------------------------------


def test_get_color_hex_for_hex_input():
    """A 7-char hex string is returned as a one-element list (the
    PR #495 regression case)."""
    out = get_color_hex("#ff0000")
    assert out == ["#ff0000"]


def test_get_color_hex_for_named_color():
    """A 2-letter color abbreviation translates to its hex."""
    out = get_color_hex("RD")
    assert isinstance(out, list) and len(out) == 1
    assert out[0].startswith("#")


def test_get_color_hex_for_two_colors():
    """A 4-char abbreviation 'BNRD' parses as two stripes (BN, RD)
    and gets a third repeated entry to render as a striped wire — the
    library's intentional widening rule for exactly-2-color wires."""
    out = get_color_hex("BNRD")
    assert len(out) == 3
    assert out[0] == out[2], "striped form should repeat the first color"
    assert all(h.startswith("#") for h in out)


def test_get_color_hex_pad_widens_single_color_to_3():
    """``pad=True`` widens a 1-color result to 3 entries so the
    rendered wire matches the thickness of multi-color wires in the
    same harness."""
    out = get_color_hex("BN", pad=True)
    assert out == [out[0]] * 3


def test_get_color_hex_no_pad_keeps_single_color():
    """``pad=False`` (the default) leaves a single-color wire as one
    entry. The PR #495 fix ensures hex inputs also count as one,
    not seven."""
    assert len(get_color_hex("BN", pad=False)) == 1
    assert len(get_color_hex("#ff0000", pad=False)) == 1


def test_translate_color_short_form():
    """``translate_color(input, 'SHORT')`` returns the short
    abbreviation."""
    assert translate_color("RD", "SHORT") == "RD"


def test_translate_color_full_name():
    """``translate_color(input, 'FULL')`` returns the full english name."""
    full = translate_color("RD", "FULL")
    assert "red" in full.lower()


def test_translate_color_hex():
    """``translate_color(input, 'hex')`` returns the lowercase hex."""
    h = translate_color("RD", "hex")
    assert h.startswith("#") and h == h.lower()
