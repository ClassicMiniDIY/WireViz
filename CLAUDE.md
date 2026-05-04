# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

WireViz is a Python CLI tool that turns YAML descriptions of cables, wiring harnesses, and connector pinouts into rendered diagrams (SVG/PNG/HTML/GraphViz) and an auto-generated Bill of Materials (TSV). Input is a single YAML file with `connectors`, `cables`, and `connections` sections; output is rendered by piping a generated GraphViz `.gv` file through `dot`.

This repo is the **upstream Python CLI**. A separate GUI front-end is being built in a sibling repo (`wireviz-gui`, not yet present in this working tree) that will eventually wrap or reuse this codebase. **All core parsing, harness-modeling, and rendering work happens here first.** Treat this repo as the engine; the GUI consumes its outputs (and likely its `wireviz.parse()` Python API). Avoid CLI-only assumptions in core modules — anything outside `wv_cli.py` should remain library-callable so the GUI can drive it programmatically.

## Commands

WireViz has **no automated test suite**. The de-facto regression check is rebuilding the examples and diffing the output.

```bash
# Install for development (from repo root)
pip install -e .

# Run the CLI on a YAML file (produces .gv .svg .png .html .bom.tsv next to input)
wireviz path/to/file.yml

# Limit output formats: g=gv h=html p=png s=svg t=tsv
wireviz -f hps path/to/file.yml

# Rebuild every demo, example, and tutorial (must cd into src/wireviz)
cd src/wireviz && python build_examples.py

# Diff regenerated outputs against the last commit (regression check after code changes)
cd src/wireviz && python build_examples.py compare

# Same, but also diff the .gv GraphViz source
cd src/wireviz && python build_examples.py compare -c

# Restore generated files from git before committing (avoid committing rebuilt artifacts in PRs)
cd src/wireviz && python build_examples.py restore

# Limit any of the above to a subset
cd src/wireviz && python build_examples.py compare -g examples tutorial demos
```

GraphViz must be installed as a system dep (`dot -V`). Code is formatted with `black` + `isort` (`isort` profile is `black`, configured in `pyproject.toml`).

CI (`.github/workflows/`) runs only `build_examples.py` across Python 3.7–3.12 — there is no `pytest`. If you add real tests, also wire them into CI.

## Architecture

The pipeline is **YAML → Harness object graph → GraphViz `.gv` → rendered SVG/PNG (+ embedded HTML) + BOM TSV**. All modules live in `src/wireviz/`.

### Entry points

- **`wv_cli.py`** — Click CLI. Reads files, handles `--prepend`, `--format`, `--output-dir`, `--output-name`, then delegates to `wireviz.parse()`. Thin wrapper; do not put logic here that the GUI would also need.
- **`wireviz.py`** — `parse()` is the real public API. Accepts a path, YAML string, or pre-parsed dict; writes any combination of `gv/svg/png/html/tsv` files and/or returns PNG/SVG bytes or the `Harness` object. The GUI will most likely call this directly. Keep its signature stable.
- **`build_examples.py`** — standalone script (run via `cd src/wireviz && python build_examples.py`, **not** as a module). Walks `examples/`, `tutorial/`, `demos/`, regenerates artifacts, and supports `compare`/`clean`/`restore` against git. Uses `sys.path` hackery to find the `wireviz` package — that's why it must be invoked from `src/wireviz/`.

### Core model

- **`DataClasses.py`** — the typed schema for everything the YAML can express: `Connector`, `Cable`, `Image`, `Options`, `Metadata`, `Tweak`, `MateComponent`/`MatePin`, plus type aliases (`Pin`, `Wire`, `Designator`, `Side`, color types). Adding a new YAML field almost always starts here.
- **`Harness.py`** — the in-memory harness graph. Holds dicts of connectors, cables, and a list of connections; provides `connect()`, BOM aggregation, and the GraphViz emission that produces the diagram. This is where most diagram-layout decisions live.
- **`wireviz.py`** (the `parse()` function below the API surface) — orchestrates: parses YAML, resolves the connection-set syntax, expands templates (the `Template.designator` separator semantics live here), builds the `Harness`, then calls into rendering.

### Rendering helpers

- **`wv_gv_html.py`** — builds the HTML-style table labels GraphViz uses for nodes (connectors, cables). All visual structure of a node is assembled here as nested HTML.
- **`wv_html.py`** + `templates/*.html` — wraps the rendered SVG and BOM into a standalone HTML page using simple string-template substitution (no Jinja).
- **`svgembed.py`** — inlines referenced raster images into the SVG so the SVG/HTML output is self-contained.
- **`wv_bom.py`** — BOM aggregation/dedup logic (`mini_bom_mode`, part-number handling, additional components). Reused for both the standalone `.bom.tsv` and the BOM table embedded in HTML.
- **`wv_colors.py`** — IEC 60757 color codes, color-scheme generators (DIN 47100, 25-pair, TIA/EIA 568), `ColorMode` (SHORT / FULL / HEX, upper/lower).
- **`wv_helper.py`** — shared utilities: `awg_equiv`/`mm2_equiv` gauge conversion, `expand` (range syntax), `tuplelist2tsv`, `smart_file_resolve` (image-path resolution against the input dir + `--prepend` dirs).

### Cross-cutting things to know

- **YAML connections syntax is positional.** A connection set is a list that *must* alternate between connector references and cable/arrow references, with pin/wire counts that match. The validation lives in `wireviz.parse()` (`check_type`, `expected_type`); errors here usually mean malformed connection lists, not a code bug.
- **`--prepend` files** are concatenated before the main YAML so users can share connector/cable libraries. Image paths from prepend files are added to `image_paths` so relative `image: src:` references still resolve.
- **The `tweak` section** (`DataClasses.Tweak`) lets users override or append raw GraphViz attributes on the generated `.gv`. It runs after normal emission — keep it that way; don't bake tweak handling into the model layer.
- **Backwards-compat shims**: `OLD_CONNECTOR_ATTR` in `Harness.py` maps deprecated keys (`pinout`, `pinnumbers`, `autogenerate`) to friendly errors. Add new deprecations there rather than silently accepting old keys.
- **Generated artifacts (`*.gv`, `*.svg`, `*.png`, `*.html`, `*.bom.tsv` under `examples/`, `tutorial/`) are checked into git.** Don't include incidental rebuilds in PRs — the project policy (per `CONTRIBUTING.md`) is that maintainers rebuild on merge. Use `build_examples.py restore` before committing.

## Contribution conventions

- Base branch for PRs is `dev`, not `master` (`master` only receives release merges).
- Format with `isort` then `black` before committing.
- Docstrings follow Google style.
- If a change touches YAML syntax, update `docs/syntax.md` in the same PR.
