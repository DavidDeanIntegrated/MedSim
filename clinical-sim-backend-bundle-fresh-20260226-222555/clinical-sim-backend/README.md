# Clinical Simulation Backend

This is a local-first MVP backend for a voice-enabled clinical simulation product.

## What is included
- FastAPI backend skeleton
- Deterministic MVP engine for hypertensive encephalopathy
- Case file for `htn_enceph_001`
- Tool/action mapping
- Parser, executor, and voice response contracts
- OpenAPI spec
- Minimal tests

## MVP run flow
1. Create a session
2. Start the hypertensive encephalopathy case
3. Send resident turns to `POST /sessions/{id}/turns`
4. Render state from `GET /sessions/{id}/state` or `/state/summary`
5. Generate the final report at `POST /sessions/{id}/reports/final`

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Run tests
```bash
pytest
```

## Important note
This bundle is an MVP scaffold, not a production-ready medical simulator. The deterministic engine is intentionally narrow and explicit so it can be tuned and audited.
