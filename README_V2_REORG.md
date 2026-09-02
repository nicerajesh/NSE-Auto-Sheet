# NSE Auto Sheet V2 — Reorganized

## Folder structure
- `src/` — all application Python modules
- `tests/` — test suite
- `.github/workflows/main.yml` — GitHub Actions workflow
- `requirements.txt` — Python dependencies
- `d1_schema.sql` — database schema

## Commands
```bash
PYTHONPATH=src python tests/test_system.py
PYTHONPATH=src python src/v3_runner.py
```

The GitHub Actions workflow has been updated to use the new `src/` and `tests/` paths.
