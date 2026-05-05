# -*- coding: utf-8 -*-
"""Shared pytest fixtures for the WireViz test suite.

Most fixtures yield Path objects pointing at small targeted YAML files
under ``tests/fixtures/``. These fixtures are intentionally separate
from the larger gallery YAMLs in ``examples/`` so test failures are
about the *thing being tested*, not about an unrelated example feature
shifting underneath us.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure the in-tree src/wireviz package is importable when running
# pytest from the repo root without a prior `pip install -e .`.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def minimal_yaml(fixtures_dir: Path) -> Path:
    """Two-pin connector + 2-wire cable. The smallest renderable harness."""
    return fixtures_dir / "minimal.yml"


@pytest.fixture
def loopback_yaml(fixtures_dir: Path) -> Path:
    """Single connector with a ``loops:`` entry, no cables — exercises
    the auto-instantiation path added by upstream PR #496."""
    return fixtures_dir / "loopback.yml"


@pytest.fixture
def loopback_template_yaml(fixtures_dir: Path) -> Path:
    """Connector template with ``loops:`` used via Template.Designator
    syntax — exercises the auto-instantiation skip added by the
    review fix on PR #1."""
    return fixtures_dir / "loopback_template.yml"


@pytest.fixture
def revisions_yaml(fixtures_dir: Path) -> Path:
    """metadata.revisions with three entries — exercises the
    %revision% placeholder."""
    return fixtures_dir / "revisions.yml"


@pytest.fixture
def per_node_tweak_yaml(fixtures_dir: Path) -> Path:
    """Per-connector / per-cable tweak with a ``@@`` placeholder."""
    return fixtures_dir / "per_node_tweak.yml"


@pytest.fixture
def hex_color_yaml(fixtures_dir: Path) -> Path:
    """Cable with a single hex-RGB wire color — exercises the wire-
    thickness padding regression fix from upstream PR #495."""
    return fixtures_dir / "hex_color.yml"


@pytest.fixture
def custom_template_yaml(fixtures_dir: Path) -> Path:
    """Harness referencing a custom HTML template by name."""
    return fixtures_dir / "custom_template.yml"


@pytest.fixture
def custom_template_dir(fixtures_dir: Path) -> Path:
    """Directory holding the ``branded.html`` template referenced by
    ``custom_template.yml``."""
    return fixtures_dir / "templates"


@pytest.fixture
def dpi_192_yaml(fixtures_dir: Path) -> Path:
    """``options.output_dpi: 192`` — twice the graphviz default."""
    return fixtures_dir / "dpi_192.yml"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    """Like ``tmp_path`` but also chdir's into it so tests that exercise
    relative-path behavior can use the temp dir as cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
