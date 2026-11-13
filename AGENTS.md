# Public Cooperative Math demo

- This repository owns the static browser UI, Python display/API bridge and demo tests.
- Mathematical source belongs to the private research `codex/math-dataset` branch. Update `runtime.zip` and `runtime.json` using this repository’s `scripts/export_runtime.py SOURCE_CHECKOUT` from a committed, verified source checkout; never patch archived solver code manually.
- GitHub Pages publishes `main` after the workflow checks. The user authorized this public demo; do not infer authorization to push the separate team repository.
- Preserve exact raw JSON for schemas and decimal strings for uint64 seeds. Parsed JavaScript numbers are for display only.
- Keep canonical model text separate from presentation markup and source IDs.
- Run automated checks on the server in this project's own virtual environment: `python -B scripts/check.py` and `node --test tests/*.test.mjs`; build with `python -B scripts/build_site.py`. Prefer Python 3.14 after compatibility checks. Install `requirements-test.txt` and Playwright Chromium; missing browser support must fail the complete check, never silently skip it. Use the Mac only for source edits, synchronization and visual inspection.
- No local venv, package cache or model weights. This demo has no Python HTTP backend. Runtime and math display CDN versions are pinned.
- Do not publish private research reports, chat history or credentials. Preserve MATH license/provenance in the runtime archive.
