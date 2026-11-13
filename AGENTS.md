# Public Cooperative Math demo

- This repository owns the static browser UI, Python display/API bridge and demo tests.
- Mathematical source belongs to the private research `codex/math-templates` branch. Update `runtime.zip` and `runtime.json` using its `scripts/export_demo_runtime.py` from a committed, verified checkout; never patch archived solver code manually.
- GitHub Pages publishes `main` after the workflow checks. The user authorized this public demo; do not infer authorization to push the separate team repository.
- Preserve exact raw JSON for schemas and decimal strings for uint64 seeds. Parsed JavaScript numbers are for display only.
- Keep canonical model text separate from presentation markup and source IDs.
- Verify with `python3 -B scripts/check.py` and `node --test tests/*.test.mjs`; build with `python3 -B scripts/build_site.py`. Browser cases use macOS WebKit/Clang; other platforms report explicit skips.
- No local venv, package cache or model weights. This demo has no Python HTTP backend. Runtime and math display CDN versions are pinned.
- Do not publish private research reports, chat history or credentials. Preserve MATH license/provenance in the runtime archive.
