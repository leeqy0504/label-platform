# Repository Guidelines

## Project Structure & Module Organization

`label_platform/` contains the FastAPI API, dataset services, database models, integrations, workflows, and background jobs. `unitrain/`, `unitrain_api/`, and `cli/` provide training adapters and command-line entry points. Migrations live in `alembic/versions/`. The React/Vite app is under `web/src/`, with pages in `app/pages`, components in `app/components`, and API clients in `services/`. Python tests mirror backend domains under `tests/`; frontend tests are colocated as `*.test.ts(x)`. Deployment files are in `deploy/` and `compose.yaml`; documentation is in `docs/`.

## Build, Test, and Development Commands

- `uv sync --dev`: install Python dependencies and developer tools.
- `docker compose up -d postgres redis`: start required local services.
- `uv run alembic upgrade head`: apply database migrations.
- `uv run uvicorn label_platform.api.app:create_app_from_env --factory --reload`: run the API locally.
- `uv run label-platform worker --simple`: run a development worker in-process.
- `uv run pytest`: run Python tests; add `-m integration` with Compose services available.
- `uv run ruff check .` and `uv run mypy`: lint and type-check Python.
- `cd web && npm ci && npm run dev`: install and run the frontend.
- `cd web && npm run test:run && npm run typecheck && npm run build`: fully verify the frontend.

## Coding Style & Naming Conventions

Use four-space indentation and a 100-character line limit for Python. Ruff targets Python 3.12, and mypy is strict for `label_platform`; type public boundaries. Use `snake_case` for Python modules/functions and `PascalCase` for classes. In TypeScript, use two-space indentation, `PascalCase.tsx` for components, `camelCase` for functions, and `@/` for imports from `web/src`.

## Testing Guidelines

Use pytest fixtures from `tests/conftest.py`; name tests `test_<behavior>`. Mark PostgreSQL/Redis tests with `@pytest.mark.integration`. Frontend tests use Vitest, Testing Library, jsdom, and MSW. Add regression coverage for fixes and migration tests for schema changes. No coverage threshold is configured; prioritize changed paths and failure cases.

## Commit & Pull Request Guidelines

Recent history favors short, imperative subjects, usually Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, or `chore:`. Keep each commit scoped to one concern. Pull requests should explain the behavior change, list verification commands, link relevant issues, call out migrations or configuration changes, and include screenshots for visible UI updates. Never commit `.env`, tokens, generated datasets, model weights, or runtime files under `var/`.
