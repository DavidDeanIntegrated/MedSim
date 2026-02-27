# File manifest

## Core app
- app/main.py
- app/core/config.py
- app/core/logging.py

## API routes
- app/api/deps.py
- app/api/routes/health.py
- app/api/routes/sessions.py
- app/api/routes/state.py
- app/api/routes/turns.py
- app/api/routes/reports.py

## Models
- app/models/common.py
- app/models/session.py
- app/models/parser.py
- app/models/engine.py
- app/models/voice.py

## Services
- app/services/session_service.py
- app/services/parser_service.py
- app/services/engine_service.py
- app/services/voice_service.py
- app/services/report_service.py

## Domain
- app/domain/case_loader.py
- app/domain/medication_library.py
- app/domain/state_machine.py

## Repository
- app/repositories/session_repo.py

## Contracts and configs
- app/contracts/medication_library.hypertensive_emergency.json
- app/contracts/patient_state.schema.json
- app/contracts/dose_response_engine.config.json
- app/contracts/tool_action_mapping.htn_enceph_001.json
- app/contracts/runtime_parser_contract.schema.json
- app/contracts/engine_executor_contract.schema.json
- app/contracts/voice_dialogue_response_contract.schema.json
- app/contracts/backend_api.openapi.yaml

## Cases
- app/data/cases/htn_enceph_001.json

## Tests
- tests/test_health.py
- tests/test_turns.py
