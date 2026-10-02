# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

WireViz is a Python CLI tool that turns YAML descriptions of cables, wiring harnesses, and connector pinouts into rendered diagrams (SVG/PNG/HTML/GraphViz) and an auto-generated Bill of Materials (TSV). Input is a single YAML file with `connectors`, `cables`, and `connections` sections; output is rendered by piping a generated GraphViz `.gv` file through `dot`.

This repo is the **upstream Python CLI**. A separate GUI front-end is being built in a sibling repo (`wireviz-gui`, not yet present in this working tree) that will eventually wrap or reuse this codebase. **All core parsing, harness-modeling, and rendering work happens here first.** Treat this repo as the engine; the GUI consumes its outputs (and likely its `wireviz.parse()` Python API). Avoid CLI-only assumptions in core modules — anything outside `wv_cli.py` should remain library-callable so the GUI can drive it programmatically.

## Commands

WireViz has both an **automated pytest suite** (`tests/`) and a separate **example-rebuild regression check** (`build_examples.py`). They serve complementary purposes — pytest validates the API and CLI surface; the example sweep validates rendered visual output across the gallery.

```bash
# Install for development (from repo root)
pip install -e .
pip install pytest

# Run the unit / integration test suite (~200 tests, ~7s)
pytest

# Run a single test file or test
pytest tests/test_regressions.py
pytest tests/test_cli.py::test_cli_template_dir

# Run the CLI on a YAML file (produces .gv .svg .png .html .bom.tsv next to input)
wireviz path/to/file.yml

# Limit output formats: g=gv h=html p=png s=svg t=tsv P=pdf
wireviz -f hps path/to/file.yml

# Stdin → stdout: pipe YAML in, get one rendered format out
cat harness.yml | wireviz -f s -O - -    > harness.svg
cat harness.yml | wireviz -f p -O - -    > harness.png

# .png input: extract the embedded YAML and re-render
wireviz harness.png

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

CI (`.github/workflows/`) runs both `pytest` (the `Tests` workflow) and `build_examples.py` (the `Create Examples` workflow) across Python 3.9–3.14. Both must pass for a PR to be considered green.

## Test suite layout (`tests/`)

- **`tests/test_smoke.py`** — every output format renders without error, has the right magic bytes, and produces the expected basic structure.
- **`tests/test_parse.py`** — the `wireviz.parse()` library API: input shapes (Path / str / dict), output shapes, return_types, source_path auto-fill, embed_yaml flag.
- **`tests/test_cli.py`** — every CLI flag via Click's `CliRunner`. Covers stdin/stdout, `.png` input round-trip, `--no-embed-yaml`, `--template-dir`, `--prepend`, error paths.
- **`tests/test_harness.py`** — `Harness` public methods, the `_render` dict shape contract, file vs stdout dispatch.
- **`tests/test_dataclasses.py`** — `Connector` / `Cable` / `Tweak` / `Options` / `Image` coercion and validation logic.
- **`tests/test_colors.py`** — color schemes (DIN/IEC/T568/TEL), hex parsing, `get_color_hex` padding behavior.
- **`tests/test_bom.py`** — BOM aggregation: identical-component dedup, ignore_in_bom, additional_bom_items, bundle category, part-number columns.
- **`tests/test_regressions.py`** — **one test per upstream-PR port + every gemini review fix.** This is where every bug we ported a fix for gets pinned down so it can never silently regress. If you change behavior touched by any of those PRs, expect tests here to fail and update them deliberately.
- **`tests/test_round_trip.py`** — PNG embed/extract, stdin→stdout pipelines, dict-input no-mutation contract.
- **`tests/test_upstream_issues.py`** — one test per upstream wireviz/WireViz issue fixed in the fork (`test_issueNNN_*`). Triage of all upstream issues: `docs/plans/2026-10-02-upstream-issue-triage.md`.
- **`tests/test_security.py`** — one test per finding of the October 2026 security audit (C1, C2, H1-H3, M1-M3, L1): always-on limits plus every `untrusted=True` rule. The `test_audit_*` tests in `test_regressions.py` pin the bugs from the same audit.

`tests/conftest.py` provides shared fixtures (paths to small targeted YAMLs in `tests/fixtures/`). The fixture YAMLs are deliberately separate from the gallery YAMLs in `examples/` so tests aren't coupled to visual gallery changes.

`pyproject.toml` configures pytest to treat unexpected warnings as errors (`filterwarnings = ["error", "ignore::SyntaxWarning"]`) so deprecations like the `re.sub(..., 1)` → `re.sub(..., count=1)` migration get caught early.

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
- **`wv_images.py`** — turns `data:image/...;base64` URIs and `.webp` files into PNG files in the harness's private temp dir (`Harness.temp_dir()`, removed when the Harness is garbage-collected). Graphviz needs a file in a format its build can read.
- **`wv_helper.py`** — shared utilities: `awg_equiv`/`mm2_equiv` gauge conversion, `expand` (range syntax), `tuplelist2tsv`, `smart_file_resolve` (image-path resolution against the input dir + `--prepend` dirs).

### Cross-cutting things to know

- **YAML connections syntax is positional.** A connection set is a list that *must* alternate between connector references and cable/arrow references, with pin/wire counts that match. The validation lives in `wireviz.parse()` (`check_type`, `expected_type`); errors here usually mean malformed connection lists, not a code bug.
- **`--prepend` files** are concatenated before the main YAML so users can share connector/cable libraries. Image paths from prepend files are added to `image_paths` so relative `image: src:` references still resolve.
- **The `tweak` section** (`DataClasses.Tweak`) lets users override or append raw GraphViz attributes on the generated `.gv`. It runs after normal emission — keep it that way; don't bake tweak handling into the model layer.
- **Backwards-compat shims**: `OLD_CONNECTOR_ATTR` in `Harness.py` maps deprecated keys (`pinout`, `pinnumbers`, `autogenerate`) to friendly errors. Add new deprecations there rather than silently accepting old keys.
- **Generated artifacts (`*.gv`, `*.svg`, `*.png`, `*.html`, `*.bom.tsv` under `examples/`, `tutorial/`) are checked into git.** Don't include incidental rebuilds in PRs — the project policy (per `CONTRIBUTING.md`) is that maintainers rebuild on merge. Use `build_examples.py restore` before committing.

## YAML loading and text escaping (load-bearing)

- **Load YAML only through `wv_helper.yaml_load()`** — never `yaml.safe_load`. It uses YAML 1.2 booleans, so `NO`/`NC`/`ON`/`Yes` stay text in pin and wire labels (upstream #305). Boolean dataclass fields convert yes/no/on/off back through `DataClasses._coerce_bools`; a new `bool` field gets this automatically, a new boolean outside a dataclass needs `wv_helper.yaml11_bool`.
- **Text that goes into a Graphviz HTML label goes through `wv_gv_html.html_text()` or `html_line_breaks()`**, which escape bare `&`, `<` and `>` while keeping tags and entities (upstream #230). The DOT parser counts angle brackets, so one bare `>` breaks the whole graph.
- **Node names and edges:** `dot.node(nohtml(name))` and `Harness._edge()` — never `dot.edge("a:p1r:e", ...)`. graphviz splits edge strings on `:` (upstream #487) and treats a name like `<X>` as an HTML label.

## Untrusted input (load-bearing)

`wireviz-gui` renders YAML sent from a browser, so this library must be safe for input its caller did not write. Design: `docs/plans/2026-10-02-october-2026-audit.md`. The contract:

- **Graphviz does not escape everything.** `options.fontname`, `<font face>` in hypertext, HTML-label `href` and `tweak` text reach the SVG raw. Never assume Graphviz output is well-formed or script-free.
- **Always on, for every caller** (`wv_safety.py`): `embed_svg_images` reads only the files in `Harness._declared_images()` (the resolved `image.src` paths) — never widen this to "any `<image>` in the SVG", that is an arbitrary local file read. `fontname` is validated. `expand()` rejects non-scalar entries (YAML alias bombs) and ranges over `MAX_EXPAND`; `pincount`/`wirecount` share the cap. PNG YAML embed/read parses raw chunks and never decodes pixels.
- **`parse(..., untrusted=True)`** sets `Harness.untrusted`, and `Harness._render` honors it (the sidecar calls `_render` directly). Untrusted: a `str` input is always YAML text (never a path); 1 MB cap; `image.src` relative and inside `image_paths`, ≤ 50 MP; `metadata.template.name` a bare name; `tweak` refused; SVG rebuilt by `sanitize_svg`; HTML values through `sanitize_html_fragment`; Graphviz via subprocess with a timeout (`Harness._pipe`).
- **Graphviz loads every `<img>` in an HTML-like label**, including one a user types into `notes`, and rasterizes it into PNG/PDF. In untrusted mode `wv_safety.check_dot_images` (called from `Harness._pipe`) allows only the exact strings `wv_gv_html.html_img_tag` generates and refuses any other `<img`. Do not replace this with attribute parsing: Graphviz reads attribute names case-insensitively and uses the last `src`. If you change the generated `<img>` markup, change it only in `html_img_tag`.
- In untrusted HTML output a metadata key may not replace a built-in placeholder (`fontname`, `bgcolor`, ...), and `metadata.template.sheetsize` must be a bare name: the templates put those values in attribute and style contexts.
- `image.src` may be a `data:image/...;base64` URI (`wv_images.py`). It is decoded to a PNG in `Harness.temp_dir()`, with the same pixel cap; in untrusted mode it is the only image source that needs no `image_paths`. Never let a data URI name a file path.
- **Every value in an HTML-like label is escaped (`html_text`) or typed.** The DOT parser ends an HTML label where `<` and `>` balance, so a raw `>` turns the rest of the label into DOT (which can load files). In untrusted mode `wv_safety.check_html_label` refuses any generated node label that is not well-formed or has unbalanced brackets — a backstop, not a replacement for escaping.
- New output paths that put user text into SVG or HTML must go through the same sanitizers when `untrusted` is set, and get a test in `tests/test_security.py`.
- `parse()` never mutates its arguments: `image_paths` is copied, dict input is deep-copied, each connection set is deep-copied before expansion.
- `options.output_dpi` defaults to `None`. Graphviz's `dpi` also scales SVG/PDF by dpi/72, so a non-None default changes every vector output.

## Contribution conventions

- Base branch for PRs is `dev`, not `master` (`master` only receives release merges).
- Format with `isort` then `black` before committing.
- Docstrings follow Google style.
- If a change touches YAML syntax, update `docs/syntax.md` in the same PR.
