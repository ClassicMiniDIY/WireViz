# -*- coding: utf-8 -*-
"""Coverage of the typed dataclasses in ``DataClasses.py`` — coercion,
validation, default behavior. These are the schema for everything
the YAML can express; if any of them drift, every consumer breaks."""

import pytest

from wireviz.DataClasses import Cable, Connector, Image, Options, Tweak


# --- Connector --------------------------------------------------------------


def test_connector_pincount_inferred_from_pinlabels():
    """Without an explicit pincount, the connector derives one from
    the longest of pins/pinlabels/pincolors."""
    c = Connector(name="X1", pinlabels=["A", "B", "C"])
    assert c.pincount == 3
    assert c.pins == [1, 2, 3]


def test_connector_explicit_pincount_wins():
    """An explicit pincount is preserved even when shorter lists are
    also present."""
    c = Connector(name="X1", pincount=5, pinlabels=["A", "B"])
    assert c.pincount == 5
    assert c.pins == [1, 2, 3, 4, 5]


def test_connector_simple_style_caps_pincount_to_1():
    c = Connector(name="X1", style="simple", pinlabels=["A"])
    assert c.pincount == 1


def test_connector_simple_style_rejects_multi_pin():
    with pytest.raises(Exception, match="simple may only have one pin"):
        Connector(name="X1", style="simple", pincount=2)


def test_connector_no_pin_info_raises():
    """A connector with no pincount, pins, pinlabels, or pincolors
    can't be rendered and is rejected at construction."""
    with pytest.raises(Exception, match="at least one"):
        Connector(name="X1")


def test_connector_duplicate_pins_raise():
    with pytest.raises(Exception, match="Pins are not unique"):
        Connector(name="X1", pins=[1, 1, 2])


# --- Cable ------------------------------------------------------------------


def test_cable_gauge_str_with_unit_parsed():
    """``gauge: '0.25 mm2'`` splits into the numeric prefix and a unit
    string (with the U+00B2 superscript-2 substitution applied).
    Note: ``gauge`` is kept as a string after splitting — the project's
    convention is to preserve the original numeric token for display.
    """
    c = Cable(name="W1", gauge="0.25 mm2", length=0.1, color_code="DIN", wirecount=2)
    assert c.gauge == "0.25"
    assert c.gauge_unit == "mm²"


def test_cable_gauge_awg_uppercased():
    c = Cable(name="W1", gauge="22 AWG", length=0.1, color_code="DIN", wirecount=2)
    assert c.gauge == "22"
    assert c.gauge_unit == "AWG"


def test_cable_gauge_numeric_assumes_mm2():
    """A bare numeric gauge gets ``mm²`` as the default unit and stays
    numeric (no string round-trip happens for numeric inputs)."""
    c = Cable(name="W1", gauge=0.5, length=0.1, color_code="DIN", wirecount=2)
    assert c.gauge == 0.5
    assert c.gauge_unit == "mm²"


def test_cable_length_with_unit():
    c = Cable(
        name="W1",
        gauge="0.25 mm2",
        length="2.5 ft",
        color_code="DIN",
        wirecount=2,
    )
    assert c.length == 2.5
    assert c.length_unit == "ft"


def test_cable_length_non_numeric_raises():
    with pytest.raises(Exception, match="Length must be a number"):
        Cable(
            name="W1",
            gauge="0.25 mm2",
            length="not a number",
            color_code="DIN",
            wirecount=2,
        )


# --- Tweak coercion --------------------------------------------------------


def test_tweak_default_fields():
    """Default ``Tweak()`` has all-None fields — the no-tweak case."""
    t = Tweak()
    assert t.placeholder is None
    assert t.override is None
    assert t.append is None


def test_connector_tweak_dict_coerced_to_tweak():
    """A dict literal in the YAML position for ``tweak:`` is coerced
    into a Tweak instance by ``Connector.__post_init__``."""
    c = Connector(
        name="X1",
        pinlabels=["A"],
        tweak={"placeholder": "@@", "append": ["@@_extra"]},
    )
    assert isinstance(c.tweak, Tweak)
    assert c.tweak.placeholder == "@@"
    assert c.tweak.append == ["@@_extra"]


def test_cable_tweak_dict_coerced_to_tweak():
    c = Cable(
        name="W1",
        gauge="0.25 mm2",
        length=0.1,
        color_code="DIN",
        wirecount=2,
        tweak={"append": ["foo"]},
    )
    assert isinstance(c.tweak, Tweak)


# --- Options ---------------------------------------------------------------


def test_options_default_dpi():
    """``output_dpi`` defaults to 96.0 — Graphviz's own default for
    non-PostScript renderers, so existing harnesses are unchanged."""
    o = Options()
    assert o.output_dpi == 96.0


def test_options_dpi_can_be_none():
    """``output_dpi: None`` is a valid value meaning "let graphviz
    pick its renderer-specific default" (see the PR #4 review fix)."""
    o = Options(output_dpi=None)
    assert o.output_dpi is None


def test_options_bgcolor_defaults_cascade():
    """When the per-element bgcolor fields are unset, they cascade
    from ``bgcolor`` (white by default)."""
    o = Options()
    assert o.bgcolor == "WH"
    # bgcolor_node falls back to bgcolor
    assert o.bgcolor_node == "WH"
    # bgcolor_connector falls back to bgcolor_node
    assert o.bgcolor_connector == "WH"


# --- Image -----------------------------------------------------------------


def test_image_scale_default():
    """When neither width nor height is set, scale defaults to 'false'."""
    img = Image(src="logo.png")
    assert img.scale == "false"


def test_image_scale_both_when_dimensions_given():
    """Explicit width + height locks scale to 'both'."""
    img = Image(src="logo.png", width=100, height=80)
    assert img.scale == "both"
    # And fixedsize gets set automatically
    assert img.fixedsize is True
