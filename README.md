# Network Simulator Backend

Backend for an AI-powered 3D networking learning and troubleshooting simulator.

## Technology Stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy
- Local AI System (CPU-first)
- Custom deterministic Network Simulation Engine

## Architecture

The backend follows a **Modular Monolith Architecture**, separating application modules, infrastructure, and the simulation engine.

### Application Structure

- `app/core/`: Shared configuration, exceptions, and common utilities.
- `app/db/`: PostgreSQL connection and persistence infrastructure.
- `app/modules/projects/`: Project management and lifecycle.
- `app/modules/topology/`: Network topology and device configuration management.
- `app/modules/simulation/`: Simulation orchestration, API handling, and snapshot preparation.
- `app/modules/ai/`: AI request routing, context building, local LLM integration, retrieval, and response validation.
- `app/modules/logs/`: Project and simulation logging.
- `app/engine/`: Pure Python deterministic network simulation engine.
- `tests/unit/`: Unit tests for individual components.
- `tests/integration/`: Integration tests between components.

## Quality checks

- Windows: `.\scripts\check.ps1`
- Any OS (Linux/macOS/Windows): `python scripts/check.py`
- Or via venv: `.venv/bin/python scripts/check.py`

## Local database

PostgreSQL is the only supported database. `scripts/dev_db.py` starts an
embedded PostgreSQL instance (the `pgserver` package from the `testing` extra)
on `127.0.0.1:5432` and persists its data in `.pgdata/`, so no system-wide
install or Docker is needed:

- Windows: `.venv\Scripts\python.exe scripts\dev_db.py --migrate`
- Linux/macOS: `.venv/bin/python scripts/dev_db.py --migrate`

`--migrate` applies the Alembic migrations. The port matches the default
`SYNTRA_DATABASE_URL`, so no environment variable is required; set that variable
to use an existing PostgreSQL server instead. Ctrl+C stops the server and keeps
the data directory.

For a GUI, install the VS Code [PostgreSQL extension](https://marketplace.visualstudio.com/items?itemName=ms-ossdata.vscode-pgsql).
`.vscode/settings.json` defines a "Syntra local (dev_db.py)" connection in the
"Local" server group, so the schema and data can be browsed from the PostgreSQL
view.

## Architectural Rules

1. The Simulation Engine is the authoritative source of network connectivity and Ping results.
2. `app/engine/` must remain independent of FastAPI, PostgreSQL, SQLAlchemy, and AI dependencies.
3. The AI System may explain simulation results but must not override or modify them.
4. The AI System targets local CPU-first inference without requiring an external AI API at runtime.
5. Domain models and persistence models must remain conceptually separate.
6. Unapproved network behavior, data contracts, and AI implementation details must not be treated as finalized requirements.

## Current Development Status

Milestone M0 - Development Foundation.

Current architecture and requirements are based on the latest approved Phase 1 Documentation baseline.

Detailed network validation, Ping and Static Routing behavior, API contracts, database schema, and AI model selection will be finalized as the related team outputs are reviewed and approved.