# Dataset, Label Studio, and UnitTrain Platform Delivery Roadmap

**Source design:** `/Users/lee/Desktop/2026-07-15-dataset-labelstudio-unitrain-platform-design.md` (status: approved)

**Reference workflow:** `/Users/lee/Downloads/SAM3 微调标注流水线和 Label Studio.md`, section 8 and appendices C.5-C.14

## Delivery Boundary

The approved design spans four independently testable subsystems. Implement them in order so each phase leaves a usable vertical slice and a stable contract for the next phase.

1. **Platform foundation and dataset versions**
   - FastAPI application, PostgreSQL metadata, authentication, roles, audit events, Redis/RQ worker.
   - Approved-root browsing and safe path resolution.
   - Raw image, COCO Detection, COCO Instance Segmentation, and Label Studio export input adapters.
   - `platform-coco-v1` normalization, validation, immutable publication, and dataset UI backed by real APIs.
   - Detailed plan: `docs/superpowers/plans/2026-07-15-platform-foundation-datasets.md`.

2. **Label Studio review sessions**
   - Label Studio REST connector compatible with the installed Label Studio 1.13.1 service.
   - Dedicated project creation, label config, local storage, idempotent task import, progress reconciliation, and deep links.
   - Server-side `BRUSH_TO_COCO` export ingestion, raw export retention, validation, and child-version publication.
   - No Label Studio database writes and no bulk replacement after human editing starts.

3. **UnitTrain service and platform integration**
   - A thin UnitTrain HTTP service around the existing CLI, with stable run IDs, process monitoring, logs, metrics, stop, model, and evaluation endpoints.
   - Canonical-to-UnitTrain export profiles that never mutate a ready version.
   - Platform training/model APIs and real training/model frontend views.
   - Contract tests run without GPU by injecting a fake process launcher; an environment-enabled smoke test remains separately marked.

4. **Operations, recovery, and end-to-end acceptance**
   - Docker Compose services for PostgreSQL, Redis, API, worker, web, Label Studio, UnitTrain API, and Nginx.
   - Reconciliation jobs, retry controls, audit administration, metrics, structured logs, and backup/restore documentation.
   - Ten-image integration test and acceptance checklist covering all twelve criteria in the approved design.

## Cross-Phase Decisions

- Use Python 3.12 through `uv`; the macOS system Python 3.9 is not a supported runtime.
- Use FastAPI, synchronous SQLAlchemy 2, Alembic, PostgreSQL, Redis, and RQ with one worker process.
- Use SQLite only for isolated unit tests; production and integration tests use PostgreSQL.
- Keep Label Studio and UnitTrain behind typed connector protocols. Tests inject fakes at those boundaries.
- Reuse the existing React/Vite frontend prototype by renaming it to `web/`, retaining its restrained operational layout, and replacing mock services with a typed HTTP client.
- Use Label Studio REST APIs only. The reference document's direct SQLite update and legacy-token mutation are explicitly excluded.
- Store secrets in environment variables. The Label Studio token shown in the reference document must never be copied into repository files or test fixtures.
- Preserve existing UniTrain source code and configure it through a service wrapper; do not require a local GPU environment for platform development.

## Completion Gate Per Phase

Each phase requires fresh evidence from its unit tests, integration tests, linters, type checks, and builds before the next phase begins. A phase is not complete while its documented verification command is failing or skipped without an explicit environment limitation.
