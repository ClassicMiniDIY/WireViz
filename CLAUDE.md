# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WireViz is a Python tool for documenting cables, wiring harnesses, and connector pinouts. It converts YAML-formatted input files into graphical outputs (SVG, PNG, HTML) and Bills of Materials (BOM) using GraphViz.

## Development Commands

### Installation (Development)
```bash
pip install -e .
```

**System Dependency:** GraphViz must be installed separately (e.g., `brew install graphviz` on macOS).

### Build/Test Examples
From the `src/wireviz/` directory:
```bash
python build_examples.py                # Build all generated files
python build_examples.py compare        # Compare against last commit
python build_examples.py clean          # Delete generated files
python build_examples.py restore        # Restore from last commit
```

Options:
- `-g examples|tutorial|demos` - Limit to specific groups
- `-b <branch>` - Compare/restore from specific branch

### Code Formatting (Required Before PR)
```bash
isort src/
black src/
```

## Architecture

### Core Data Flow
```
YAML Input → parse() → DataClasses → Harness → GraphViz → Output Files
```

### Key Modules (`src/wireviz/`)

| Module | Purpose |
|--------|---------|
| `wireviz.py` | Main `parse()` function - entry point for YAML processing |
| `Harness.py` | `Harness` class - assembles components and generates GraphViz output |
| `DataClasses.py` | Data structures: `Connector`, `Cable`, `Metadata`, `Options`, `Tweak` |
| `wv_cli.py` | Click-based CLI (`wireviz` command) |
| `wv_bom.py` | Bill of Materials generation and aggregation |
| `wv_colors.py` | Wire color schemes (DIN 47100, IEC 60757, 25-pair, T568A/B) |
| `wv_helper.py` | Utilities (AWG↔mm² conversion, pin expansion, file I/O) |
| `wv_html.py` | HTML template rendering |
| `wv_gv_html.py` | GraphViz HTML table formatting |

### Entry Points

**CLI:**
```bash
wireviz [FILE] [-f FORMAT] [-o OUTPUT_DIR] [-O OUTPUT_NAME]
```

**Programmatic:**
```python
from wireviz import wireviz
wireviz.parse(
    inp=<Path|str|Dict>,           # YAML file, string, or dict
    return_types="png"|"svg"|"harness",
    output_formats="csv"|"gv"|"html"|"png"|"pdf"|"svg"|"tsv"
)
```

### YAML Structure
Input files have these main sections:
- `connectors:` - Connector definitions with pinouts
- `cables:` - Cable/wire definitions with gauges and color codes
- `connections:` - Wiring connections between connectors/cables
- `metadata:` - Title, description, notes
- `options:` - Global rendering options
- `tweak:` - GraphViz output customizations

## Testing Approach

There is no pytest/unittest framework. Testing is done via example validation:
1. Run `python build_examples.py` after code changes
2. Run `python build_examples.py compare` to verify output differences are expected
3. Run `python build_examples.py restore` before committing to avoid including generated files

## Branch Strategy

- `master` - Main production branch
- `dev` - Development branch (create feature branches from here)
- PRs should target `dev` branch

## Documentation Style

Use Google Style docstrings: https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html
