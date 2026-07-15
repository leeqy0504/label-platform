# Platform Foundation and Dataset Versions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a locally runnable authenticated platform that safely registers all four first-release dataset inputs, publishes validated immutable `platform-coco-v1` versions, and displays real dataset state in the supplied frontend.

**Architecture:** A FastAPI application owns metadata and workflow transitions in PostgreSQL while an RQ worker performs scans and version publication. Dataset adapters normalize source-specific records into one in-memory contract, a publisher writes an atomic managed version, and the React/Vite frontend calls only the platform API. External Label Studio review orchestration and UnitTrain execution remain behind future connector phases, but Label Studio export files are accepted as an input format in this phase.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, synchronous SQLAlchemy 2, Alembic, PostgreSQL, Redis/RQ, Pillow, pycocotools, Label Studio SDK converter utilities, pytest, React 18, TypeScript, Vite, Vitest, Testing Library, MSW.

---

## File Map

Create the backend under `label_platform/` without changing the existing `unitrain/` package:

```text
label_platform/
├── api/
│   ├── app.py                 # application factory and health route
│   ├── dependencies.py        # DB session and current-user dependencies
│   └── routes/
│       ├── auth.py            # login, logout, current user
│       ├── datasets.py        # roots, tree, scan, register, list, detail
│       └── jobs.py            # background-job status
├── auth/
│   ├── passwords.py           # Argon2 password hashing
│   └── sessions.py            # signed HttpOnly session cookie
├── datasets/
│   ├── contracts.py           # normalized adapter dataclasses
│   ├── detection.py           # source-format detection
│   ├── image_adapter.py       # unannotated image directories
│   ├── coco_adapter.py        # detection and instance COCO
│   ├── labelstudio_adapter.py # JSON/ZIP Label Studio input
│   ├── normalize.py           # IDs, categories, masks, bboxes, splits
│   ├── validate.py            # canonical validation report
│   ├── publisher.py           # staged copy, manifest, atomic publish
│   └── service.py             # registration workflow and DB transitions
├── db/
│   ├── base.py                # declarative base and timestamps
│   ├── session.py             # engine/session factory
│   └── models/
│       ├── accounts.py        # users and allowed roots
│       ├── datasets.py        # dataset/source/version/item models
│       ├── jobs.py            # jobs and audit events
│       └── __init__.py        # metadata import surface
├── jobs/
│   ├── queue.py               # queue protocol and RQ implementation
│   └── tasks.py               # serializable worker entry points
├── config.py                  # environment-backed settings
└── cli.py                     # create-admin and worker entry points
```

The existing frontend moves from `视觉数据集管理平台/` to `web/`. Retain the existing pages/components, replace `src/services/api.ts`, and add auth and test support. Deployment files for this phase are `compose.yaml`, `deploy/api.Dockerfile`, `deploy/web.Dockerfile`, and `.env.example`.

## Task 1: Establish the Python Toolchain and API Health Contract

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `.python-version`
- Create: `label_platform/__init__.py`
- Create: `label_platform/config.py`
- Create: `label_platform/api/__init__.py`
- Create: `label_platform/api/app.py`
- Create: `tests/api/test_health.py`
- Create: `tests/conftest.py`
- Generate: `uv.lock`

- [ ] **Step 1: Add the failing health test**

```python
from fastapi.testclient import TestClient

from label_platform.api.app import create_app
from label_platform.config import Settings


def test_health_reports_service_ready(tmp_path):
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        managed_data_root=tmp_path / "managed",
        session_secret="test-secret-with-at-least-32-characters",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "label-platform-api"}
```

- [ ] **Step 2: Run the test and verify the missing package failure**

Run: `uv run --python 3.12 pytest tests/api/test_health.py -v`

Expected: FAIL during import because `label_platform.api.app` does not exist.

- [ ] **Step 3: Configure the project and implement the application factory**

Set `requires-python = ">=3.12,<3.14"` and add runtime dependencies for `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `redis`, `rq`, `pwdlib[argon2]`, `itsdangerous`, `httpx`, `pillow`, `numpy`, `pycocotools`, `label-studio-sdk`, and `pyyaml`. Add a `dev` dependency group containing `pytest`, `pytest-cov`, `ruff`, and `mypy`. Include `label_platform*` in setuptools discovery.

Implement settings with the exact fields used throughout this phase:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    redis_url: str = "redis://localhost:6379/0"
    managed_data_root: Path = Path("./var/managed")
    session_secret: str
    session_max_age_seconds: int = 28800
    secure_cookies: bool = False
```

`create_app(settings)` stores settings on `app.state`, creates the managed root during lifespan, and registers `GET /api/health` with the exact response asserted above.

- [ ] **Step 4: Lock dependencies and run the focused test**

Run: `uv lock && uv run --python 3.12 pytest tests/api/test_health.py -v`

Expected: PASS, 1 test.

- [ ] **Step 5: Run static checks and commit**

Run: `uv run ruff check label_platform tests && uv run mypy label_platform`

Expected: both commands exit 0.

```bash
git add .python-version .gitignore pyproject.toml uv.lock label_platform tests
git commit -m "feat: scaffold platform API"
```

## Task 2: Add the Database Model and Migration Baseline

**Files:**
- Create: `label_platform/domain/__init__.py`
- Create: `label_platform/domain/enums.py`
- Create: `label_platform/db/__init__.py`
- Create: `label_platform/db/base.py`
- Create: `label_platform/db/session.py`
- Create: `label_platform/db/models/accounts.py`
- Create: `label_platform/db/models/datasets.py`
- Create: `label_platform/db/models/jobs.py`
- Create: `label_platform/db/models/__init__.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial.py`
- Create: `tests/db/test_models.py`

- [ ] **Step 1: Write a failing persistence test**

```python
def test_dataset_version_keeps_schema_and_parent(db_session, user, allowed_root):
    dataset = Dataset(name="warehouse", description="", created_by_id=user.id)
    source = DatasetSource(
        dataset=dataset,
        allowed_root_id=allowed_root.id,
        relative_path="incoming/warehouse",
        normalized_path="/srv/data/incoming/warehouse",
        source_format=SourceFormat.COCO_INSTANCE,
        task_type=TaskType.INSTANCE_SEGMENTATION,
    )
    v1 = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.READY,
        root_path="warehouse/versions/v1",
        manifest_path="manifest.json",
        annotation_path="annotations/instances.coco.json",
        class_schema=[{"id": 1, "name": "cargo"}],
    )
    v2 = DatasetVersion(
        dataset=dataset,
        version_number=2,
        parent=v1,
        status=VersionStatus.BUILDING,
        class_schema=v1.class_schema,
    )
    db_session.add_all([source, v2])
    db_session.commit()

    assert v2.parent_id == v1.id
    assert v2.class_schema == [{"id": 1, "name": "cargo"}]
    assert dataset.sources == [source]
```

- [ ] **Step 2: Run the test and confirm model imports fail**

Run: `uv run pytest tests/db/test_models.py -v`

Expected: FAIL because the database models are not defined.

- [ ] **Step 3: Implement enums, models, and test fixtures**

Define string enums with these values:

```python
class UserRole(StrEnum):
    ADMIN = "admin"
    DATA_ENGINEER = "data_engineer"
    REVIEWER = "reviewer"

class SourceFormat(StrEnum):
    IMAGE_DIRECTORY = "image_directory"
    COCO_DETECTION = "coco_detection"
    COCO_INSTANCE = "coco_instance"
    LABEL_STUDIO = "label_studio"

class TaskType(StrEnum):
    DETECTION = "detection"
    INSTANCE_SEGMENTATION = "instance_segmentation"

class VersionStatus(StrEnum):
    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    INVALID = "invalid"

class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

Use UUID strings as primary keys and UTC timestamp columns. Implement `User`, `AllowedRoot`, `Dataset`, `DatasetSource`, `DatasetVersion`, `DatasetItem`, `BackgroundJob`, and `AuditEvent` with the fields in sections 8 and 18 of the approved design. Store class schemas and structured job errors in JSON columns. Add unique constraints for `(dataset_id, version_number)`, `(version_id, sample_key)`, and allowed-root paths.

Use a test session fixture backed by a temporary SQLite file with foreign keys enabled. Production `create_engine_from_settings` uses the configured PostgreSQL URL.

- [ ] **Step 4: Add and verify the initial Alembic migration**

The migration must create all tables, foreign keys, indexes, unique constraints, and enum-compatible string columns. It must downgrade in reverse dependency order.

Run: `uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head`

Expected: all three commands exit 0 against `PLATFORM_DATABASE_URL` pointing to a disposable PostgreSQL database.

- [ ] **Step 5: Run model tests and commit**

Run: `uv run pytest tests/db/test_models.py -v`

Expected: PASS.

```bash
git add alembic.ini alembic label_platform/domain label_platform/db tests
git commit -m "feat: add platform metadata model"
```

## Task 3: Implement Account Authentication and Role Enforcement

**Files:**
- Create: `label_platform/auth/__init__.py`
- Create: `label_platform/auth/passwords.py`
- Create: `label_platform/auth/sessions.py`
- Create: `label_platform/api/dependencies.py`
- Create: `label_platform/api/routes/__init__.py`
- Create: `label_platform/api/routes/auth.py`
- Create: `label_platform/api/routes/users.py`
- Create: `label_platform/cli.py`
- Modify: `label_platform/api/app.py`
- Modify: `pyproject.toml`
- Create: `tests/api/test_auth.py`

- [ ] **Step 1: Write failing login and authorization tests**

```python
def test_login_sets_http_only_session_cookie(client, user_factory):
    user_factory(email="engineer@example.test", password="correct-horse", role="data_engineer")

    response = client.post(
        "/api/auth/login",
        json={"email": "engineer@example.test", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "data_engineer"
    cookie = response.headers["set-cookie"]
    assert "platform_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_data_engineer_cannot_call_admin_probe(authenticated_client):
    response = authenticated_client.get("/api/auth/admin-probe")
    assert response.status_code == 403
```

- [ ] **Step 2: Run the tests and verify 404 responses**

Run: `uv run pytest tests/api/test_auth.py -v`

Expected: FAIL because the auth routes do not exist.

- [ ] **Step 3: Implement passwords, signed sessions, and route dependencies**

Use `pwdlib.PasswordHash.recommended()` for password hashes. Use `itsdangerous.URLSafeTimedSerializer` with salt `label-platform-session` to sign only `{"user_id": <uuid>}`. Configure the cookie as `HttpOnly`, `SameSite=strict`, `path=/`, and `Secure` according to settings.

Expose:

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

Expose administrator-only account management:

```text
GET   /api/admin/users
POST  /api/admin/users
PATCH /api/admin/users/{user_id}
```

Creation accepts name, email, role, and an initial password; email is normalized and unique. Patch can change name, role, and active status but cannot deactivate or demote the last active administrator. Responses never include `password_hash`.

`current_user` returns 401 for absent, invalid, expired, inactive, or deleted users. `require_roles(*roles)` returns 403 for a valid user outside the accepted roles. The test-only probe is registered only when `settings.environment == "test"`.

Add `label-platform = "label_platform.cli:main"` and implement:

```text
uv run label-platform create-admin --email admin@example.internal --name Administrator
```

The command reads a password twice from `getpass`, rejects mismatches, hashes it, and creates an active administrator.

- [ ] **Step 4: Verify auth behavior and commit**

Run: `uv run pytest tests/api/test_auth.py -v`

Expected: PASS for valid login, invalid login, logout, expired cookie, inactive user, and role checks.

```bash
git add pyproject.toml uv.lock label_platform/auth label_platform/api label_platform/cli.py tests
git commit -m "feat: add platform account authentication"
```

## Task 4: Enforce Approved Source Roots and Safe Directory Browsing

**Files:**
- Create: `label_platform/datasets/__init__.py`
- Create: `label_platform/datasets/paths.py`
- Create: `label_platform/api/routes/roots.py`
- Modify: `label_platform/api/app.py`
- Create: `tests/datasets/test_paths.py`
- Create: `tests/api/test_roots.py`

- [ ] **Step 1: Write failing traversal and symlink tests**

```python
def test_resolve_source_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "approved"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SourcePathError, match="approved root"):
        resolve_source_path(root, "escape")


@pytest.mark.parametrize("relative", ["../outside", "/etc", "a/../../outside"])
def test_resolve_source_path_rejects_traversal(tmp_path, relative):
    root = tmp_path / "approved"
    root.mkdir()
    with pytest.raises(SourcePathError):
        resolve_source_path(root, relative)
```

- [ ] **Step 2: Run the path tests and verify missing implementation**

Run: `uv run pytest tests/datasets/test_paths.py -v`

Expected: FAIL because `resolve_source_path` is undefined.

- [ ] **Step 3: Implement containment checks and directory listing**

`resolve_source_path(root, relative)` requires a relative POSIX path, resolves both root and candidate with `strict=True`, checks `candidate.is_relative_to(root)`, requires a directory, and rejects every symlink component from root to candidate. `iter_safe_files` rejects symlinks, devices, sockets, FIFOs, and non-regular files.

Expose authenticated routes:

```text
GET /api/source-roots
GET /api/source-roots/{root_id}/tree?path=<relative-path>
POST /api/admin/source-roots
PATCH /api/admin/source-roots/{root_id}
```

Return only direct child directories plus supported image/JSON/ZIP files. Administrators can see all root metadata; data engineers receive only active roots. Never return an arbitrary filesystem path supplied by the browser.

Administrator creation resolves the submitted absolute path once, requires an existing directory, and stores the normalized result. Patch changes label, description, or active status; it never changes the stored path. Add API tests for duplicate roots, nonexistent paths, non-admin access, and hiding inactive roots from data engineers.

- [ ] **Step 4: Run path and API tests and commit**

Run: `uv run pytest tests/datasets/test_paths.py tests/api/test_roots.py -v`

Expected: PASS, including traversal, symlink escape, special file, inactive root, and role cases.

```bash
git add label_platform/datasets label_platform/api tests
git commit -m "feat: secure approved source roots"
```

## Task 5: Detect Sources and Adapt Unannotated Image Directories

**Files:**
- Create: `label_platform/datasets/contracts.py`
- Create: `label_platform/datasets/detection.py`
- Create: `label_platform/datasets/image_adapter.py`
- Create: `tests/datasets/test_detection.py`
- Create: `tests/datasets/test_image_adapter.py`

- [ ] **Step 1: Write failing detection and duplicate-name tests**

```python
def test_detects_plain_image_directory(image_factory, tmp_path):
    image_factory(tmp_path / "camera-a" / "frame.jpg", size=(20, 10))
    assert detect_source(tmp_path).format is SourceFormat.IMAGE_DIRECTORY


def test_image_adapter_uses_relative_path_in_sample_key(image_factory, tmp_path):
    image_factory(tmp_path / "a" / "frame.jpg", size=(20, 10))
    image_factory(tmp_path / "b" / "frame.jpg", size=(30, 15))

    source = ImageDirectoryAdapter().read(tmp_path, dataset_id="dataset-1", categories=["cargo"])

    assert len(source.images) == 2
    assert source.images[0].sample_key != source.images[1].sample_key
    assert {item.relative_path for item in source.images} == {"a/frame.jpg", "b/frame.jpg"}
```

- [ ] **Step 2: Run tests and verify missing adapters**

Run: `uv run pytest tests/datasets/test_detection.py tests/datasets/test_image_adapter.py -v`

Expected: FAIL on missing adapter modules.

- [ ] **Step 3: Define the adapter contract and implement raw-image scanning**

Use these source-neutral types:

```python
@dataclass(frozen=True)
class SourceImage:
    source_path: Path
    relative_path: str
    sample_key: str
    width: int
    height: int
    file_size: int
    sha256: str
    split: str | None = None
    group_key: str | None = None

@dataclass(frozen=True)
class SourceAnnotation:
    image_key: str
    category_name: str
    bbox: tuple[float, float, float, float] | None
    segmentation: dict[str, object] | list[list[float]] | None

@dataclass(frozen=True)
class SourceDataset:
    format: SourceFormat
    task_type: TaskType
    images: tuple[SourceImage, ...]
    annotations: tuple[SourceAnnotation, ...]
    categories: tuple[str, ...]
    category_id_mapping: dict[str, int]
```

Support `.jpg`, `.jpeg`, `.png`, and `.webp` case-insensitively. Read dimensions after `ImageOps.exif_transpose`, hash file bytes in chunks, normalize relative paths to POSIX, and derive `sample_key` as SHA-256 of `<dataset-id>\0<relative-path>`. Reject duplicate normalized paths and images Pillow cannot decode.

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/datasets/test_detection.py tests/datasets/test_image_adapter.py -v`

Expected: PASS for supported images, nested duplicate names, corrupt media, EXIF orientation, and empty directories.

```bash
git add label_platform/datasets tests/datasets
git commit -m "feat: adapt raw image directories"
```

## Task 6: Adapt COCO and Label Studio Export Inputs

**Files:**
- Create: `label_platform/datasets/coco_adapter.py`
- Create: `label_platform/datasets/labelstudio_adapter.py`
- Modify: `label_platform/datasets/detection.py`
- Create: `tests/fixtures/coco_detection.json`
- Create: `tests/fixtures/coco_instance.json`
- Create: `tests/fixtures/labelstudio_rectangle.json`
- Create: `tests/datasets/test_coco_adapter.py`
- Create: `tests/datasets/test_labelstudio_adapter.py`

- [ ] **Step 1: Write failing adapter behavior tests**

```python
def test_coco_instance_adapter_preserves_source_category_mapping(coco_instance_source):
    source = CocoAdapter().read(coco_instance_source, dataset_id="dataset-1")

    assert source.format is SourceFormat.COCO_INSTANCE
    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert source.categories == ("person", "rack")
    assert source.category_id_mapping == {"source:0": 1, "source:8": 2}


def test_labelstudio_zip_rejects_escaping_member(tmp_path):
    archive = tmp_path / "export.zip"
    write_zip(archive, {"../outside.json": b"{}"})

    with pytest.raises(SourceFormatError, match="unsafe archive member"):
        LabelStudioExportAdapter().read(archive, dataset_id="dataset-1")
```

- [ ] **Step 2: Run focused tests and confirm missing classes**

Run: `uv run pytest tests/datasets/test_coco_adapter.py tests/datasets/test_labelstudio_adapter.py -v`

Expected: FAIL because both adapters are absent.

- [ ] **Step 3: Implement COCO detection and instance parsing**

Require `images`, `annotations`, and `categories` arrays. Resolve every `file_name` relative to the source root and apply the approved-root safety checks. Preserve original category IDs in `category_id_mapping`, normalize canonical category IDs by source category order to positive integers starting at one, and classify a dataset as instance segmentation when any non-empty segmentation exists. Reject unknown image/category references, duplicate IDs, non-finite geometry, and absent image files.

- [ ] **Step 4: Implement Label Studio JSON and ZIP parsing**

Accept either native Label Studio task arrays or ZIP archives containing a native JSON file or `result_coco.json`. ZIP reading is in-memory or within a temporary directory and validates every member with `PurePosixPath`: no absolute path and no `..` component.

For native tasks:

- `rectanglelabels` becomes COCO `[x, y, width, height]` using percentage coordinates and the recorded original dimensions.
- `polygonlabels` becomes polygon segmentation.
- `brushlabels` uses `label_studio_sdk.converter.brush.decode_rle`, then pycocotools RLE encoding.
- result label values must exist in the discovered/frozen category list.

Prefer the last non-cancelled human annotation on each task. Preserve unannotated tasks as images with no annotations.

- [ ] **Step 5: Run all adapter tests and commit**

Run: `uv run pytest tests/datasets/test_detection.py tests/datasets/test_coco_adapter.py tests/datasets/test_labelstudio_adapter.py -v`

Expected: PASS for COCO boxes, polygons, compressed/uncompressed RLE, native rectangle/brush results, plain JSON, ZIP, unknown references, and unsafe archives.

```bash
git add label_platform/datasets tests/datasets tests/fixtures
git commit -m "feat: adapt COCO and Label Studio inputs"
```

## Task 7: Normalize and Validate `platform-coco-v1`

**Files:**
- Create: `label_platform/datasets/normalize.py`
- Create: `label_platform/datasets/validate.py`
- Create: `tests/datasets/test_normalize.py`
- Create: `tests/datasets/test_validate.py`

- [ ] **Step 1: Write failing mask-authority and validation tests**

```python
def test_instance_mask_derives_bbox_and_area(source_dataset_with_mask):
    canonical = normalize_source(source_dataset_with_mask, split_seed=42)
    annotation = canonical.coco["annotations"][0]

    assert annotation["bbox"] == [2.0, 1.0, 3.0, 4.0]
    assert annotation["area"] == 12.0


def test_validator_rejects_path_escape(canonical_version):
    canonical_version.coco["images"][0]["file_name"] = "../outside.jpg"
    report = validate_canonical(canonical_version)

    assert report.valid is False
    assert report.errors[0].code == "image_path_escape"
```

- [ ] **Step 2: Run tests and verify normalization is absent**

Run: `uv run pytest tests/datasets/test_normalize.py tests/datasets/test_validate.py -v`

Expected: FAIL on missing functions.

- [ ] **Step 3: Implement deterministic normalization**

Return a `CanonicalVersion` containing the complete COCO dictionary, split membership keyed by `sample_key`, manifest data, and source-image mapping. Assign stable positive image and annotation IDs by sorted `sample_key` and source annotation order. For detection keep the source bbox. For instance segmentation decode the mask, reject empty masks, then use `mask_utils.area` and `mask_utils.toBbox`; never trust a conflicting source bbox.

When no split exists, assign groups deterministically using SHA-256 of `<seed>\0<group-or-sample-key>` with default ratios `train=0.8`, `val=0.2`, `test=0`. Require ratios to sum to one and keep each group in one split.

The manifest includes format, task type, source format, converter version, counts, class schema, category mapping, split counts, source lineage, and per-file checksums.

- [ ] **Step 4: Implement complete canonical validation**

Return structured errors with `code`, `path`, and `message`. Validate all section 16 requirements: file containment, manifest contract, unique positive IDs, known categories, finite in-bounds boxes, decodable non-empty segmentations, positive mask area, mask/bbox extent agreement within one pixel, dimensions, split existence/non-overlap, and frozen schema equality.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/datasets/test_normalize.py tests/datasets/test_validate.py -v`

Expected: PASS for valid detection/instance data and every rejection class above.

```bash
git add label_platform/datasets tests/datasets
git commit -m "feat: normalize and validate canonical datasets"
```

## Task 8: Publish Immutable Managed Dataset Versions

**Files:**
- Create: `label_platform/datasets/publisher.py`
- Create: `label_platform/datasets/service.py`
- Create: `tests/datasets/test_publisher.py`
- Create: `tests/datasets/test_registration_service.py`

- [ ] **Step 1: Write failing atomic-publication tests**

```python
def test_publish_creates_ready_layout_and_latest_link(registration_service, raw_source, managed_root):
    version = registration_service.register(raw_source.request)
    version_root = managed_root / version.dataset_id / "versions" / "v1"

    assert version.status is VersionStatus.READY
    assert (version_root / "annotations/instances.coco.json").is_file()
    assert (version_root / "splits/train.txt").is_file()
    assert (version_root / "manifest.json").is_file()
    assert (managed_root / version.dataset_id / "latest").resolve() == version_root.resolve()


def test_publish_failure_never_exposes_partial_version(registration_service, corrupt_source, managed_root):
    with pytest.raises(DatasetRegistrationError):
        registration_service.register(corrupt_source.request)

    assert not list(managed_root.rglob("v1"))
```

- [ ] **Step 2: Run tests and verify publisher absence**

Run: `uv run pytest tests/datasets/test_publisher.py tests/datasets/test_registration_service.py -v`

Expected: FAIL because publication is not implemented.

- [ ] **Step 3: Implement staged materialization and immutable publication**

Create a staging directory under `<dataset>/versions/.building-<version-id>`. Materialize every image after EXIF transpose; prefer `clonefile` on macOS or `cp --reflink=auto` only through a capability wrapper, and otherwise use `shutil.copy2`. Never use hard links. Write canonical JSON with sorted keys and newline termination, split files with one sample key per line, and the full manifest.

Validate the staged directory before `os.replace(staging, vN)`. Set all version files read-only after publication. Update `latest` through a temporary symlink plus `os.replace`. On any error remove only the known staging path, mark the database version `INVALID`, store the validation report, and leave prior ready versions untouched.

Allocate version numbers inside a database transaction while locking the dataset row on PostgreSQL. `READY` versions cannot be updated through service methods.

- [ ] **Step 4: Run publisher tests and commit**

Run: `uv run pytest tests/datasets/test_publisher.py tests/datasets/test_registration_service.py -v`

Expected: PASS for v1/v2 allocation, atomic failure, immutable files, lineage, and latest-link behavior.

```bash
git add label_platform/datasets tests/datasets
git commit -m "feat: publish immutable dataset versions"
```

## Task 9: Queue Registration Jobs and Expose Dataset APIs

**Files:**
- Create: `label_platform/jobs/__init__.py`
- Create: `label_platform/jobs/queue.py`
- Create: `label_platform/jobs/tasks.py`
- Create: `label_platform/api/routes/datasets.py`
- Create: `label_platform/api/routes/jobs.py`
- Modify: `label_platform/api/app.py`
- Modify: `label_platform/cli.py`
- Create: `tests/jobs/test_registration_job.py`
- Create: `tests/api/test_datasets.py`

- [ ] **Step 1: Write failing API/idempotency tests**

```python
def test_register_dataset_enqueues_one_idempotent_job(engineer_client, allowed_root, inline_queue):
    payload = {
        "name": "warehouse",
        "description": "cargo masks",
        "source_root_id": allowed_root.id,
        "relative_path": "incoming/warehouse",
        "categories": ["cargo"],
        "split": {"train": 0.8, "val": 0.2, "test": 0.0, "seed": 42},
        "idempotency_key": "register-warehouse-20260715",
    }

    first = engineer_client.post("/api/datasets/register", json=payload)
    second = engineer_client.post("/api/datasets/register", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert inline_queue.enqueued_count == 1
```

- [ ] **Step 2: Run tests and verify routes are missing**

Run: `uv run pytest tests/jobs/test_registration_job.py tests/api/test_datasets.py -v`

Expected: FAIL with 404 or missing imports.

- [ ] **Step 3: Implement the queue boundary and worker task**

Define a `JobQueue` protocol with `enqueue_registration(job_id: str)`. `RQJobQueue` sends only the job UUID to queue `dataset-operations`; the worker opens its own DB session and reloads all business state. `InlineJobQueue` is test-only.

The worker transitions `PENDING -> RUNNING -> SUCCEEDED|FAILED`, records stage and processed/total counts, calls `RegistrationService`, writes a concise error summary plus log path, and increments retry count on explicit retries.

Add `uv run label-platform worker`, implemented with an RQ worker listening to `dataset-operations` at concurrency one.

- [ ] **Step 4: Implement dataset and job routes**

Expose:

```text
POST /api/datasets/analyze
POST /api/datasets/register
GET  /api/datasets
GET  /api/datasets/{dataset_id}
GET  /api/datasets/{dataset_id}/versions
GET  /api/datasets/{dataset_id}/versions/{version_id}/items
GET  /api/datasets/{dataset_id}/versions/{version_id}/items/{item_id}/media
POST /api/datasets/{dataset_id}/archive
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/retry
```

Analysis is a queued job returning format, task type, counts, categories, split summary, unsupported files, and normalization errors without publishing. Registration requires a successful analysis fingerprint and rechecks source checksums before publication. List responses use `{data, meta: {page, page_size, total}}`. The media route looks up the item by dataset/version membership and serves only its canonical path after a second containment check; it never accepts a filesystem path. Archive is reversible only through an administrator patch and does not delete managed files. All mutating routes write audit events in the same transaction.

- [ ] **Step 5: Run API/job tests and commit**

Run: `uv run pytest tests/jobs/test_registration_job.py tests/api/test_datasets.py -v`

Expected: PASS for role checks, pagination, analysis, registration, progress, failure, retry, checksum change, and idempotency.

```bash
git add label_platform/jobs label_platform/api label_platform/cli.py tests
git commit -m "feat: expose queued dataset registration"
```

## Task 10: Convert the Frontend Prototype into a Tested Web Application

**Files:**
- Rename: `视觉数据集管理平台/` to `web/`
- Modify: `web/package.json`
- Create: `web/src/test/setup.ts`
- Create: `web/src/test/server.ts`
- Create: `web/src/services/http.ts`
- Replace: `web/src/services/api.ts`
- Create: `web/src/app/auth/AuthProvider.tsx`
- Create: `web/src/app/pages/LoginPage.tsx`
- Modify: `web/src/app/App.tsx`
- Modify: `web/src/app/routes.ts`
- Modify: `web/vite.config.ts`
- Create: `web/src/app/pages/LoginPage.test.tsx`

- [ ] **Step 1: Install and configure the frontend test toolchain**

Rename the directory with `git mv`. Add scripts `test`, `test:run`, and `typecheck`; add dev dependencies `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, and `typescript`. Configure Vitest for `jsdom` and `src/test/setup.ts`.

Run: `cd web && npm install`

Expected: `package-lock.json` is created and install exits 0.

- [ ] **Step 2: Write a failing login test**

```tsx
it('logs in and opens the dataset workspace', async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText('邮箱'), 'engineer@example.test');
  await userEvent.type(screen.getByLabelText('密码'), 'correct-horse');
  await userEvent.click(screen.getByRole('button', { name: '登录' }));

  expect(await screen.findByRole('heading', { name: '数据集' })).toBeInTheDocument();
});
```

MSW handles `GET /api/auth/me` with 401 followed by a successful `POST /api/auth/login` and authenticated `GET /api/datasets`.

- [ ] **Step 3: Run the test and verify the login screen is absent**

Run: `cd web && npm run test:run -- src/app/pages/LoginPage.test.tsx`

Expected: FAIL because no email field exists.

- [ ] **Step 4: Implement the typed HTTP client and auth boundary**

`request<T>` always sends `credentials: 'include'`, serializes JSON, parses structured API errors, and throws `ApiError(status, code, message, details)`. Replace all mock imports in `services/api.ts` with endpoint calls while preserving function names used by existing pages.

`AuthProvider` loads `/api/auth/me`, exposes `login`, `logout`, and `user`, and renders the quiet work-oriented login screen when unauthenticated. Routes require authentication; `/admin` additionally requires the admin role. Do not store session tokens in JavaScript storage.

- [ ] **Step 5: Run frontend checks and commit**

Run: `cd web && npm run test:run && npm run typecheck && npm run build`

Expected: all commands exit 0.

```bash
git add web
git commit -m "feat: connect frontend authentication"
```

## Task 11: Connect Dataset Registration, Lists, Details, and Job Progress

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/services/api.ts`
- Modify: `web/src/app/pages/DatasetsPage.tsx`
- Modify: `web/src/app/pages/DatasetDetailPage.tsx`
- Modify: `web/src/app/components/datasets/RegisterDatasetDialog.tsx`
- Modify: `web/src/app/components/datasets/OverviewTab.tsx`
- Modify: `web/src/app/components/datasets/FilesTab.tsx`
- Modify: `web/src/app/components/datasets/CategoriesTab.tsx`
- Modify: `web/src/app/components/datasets/VersionsTab.tsx`
- Modify: `web/src/app/hooks/useBackgroundTasks.ts`
- Create: `web/src/app/pages/DatasetsPage.test.tsx`
- Create: `web/src/app/components/datasets/RegisterDatasetDialog.test.tsx`

- [ ] **Step 1: Write failing registration workflow tests**

```tsx
it('analyzes a server directory before enabling registration', async () => {
  render(<RegisterDatasetDialog open onOpenChange={() => {}} onRegistered={() => {}} />);
  await userEvent.selectOptions(screen.getByLabelText('允许目录'), 'root-1');
  await userEvent.type(screen.getByLabelText('相对路径'), 'incoming/warehouse');
  await userEvent.click(screen.getByRole('button', { name: '分析目录' }));

  expect(await screen.findByText('COCO Instance Segmentation')).toBeInTheDocument();
  expect(screen.getByText('1,000 张图片')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '登记数据集' })).toBeEnabled();
});
```

Add a second test where analysis returns normalization errors and the registration button remains disabled.

- [ ] **Step 2: Run focused frontend tests and verify mock-shaped UI fails**

Run: `cd web && npm run test:run -- src/app/pages/DatasetsPage.test.tsx src/app/components/datasets/RegisterDatasetDialog.test.tsx`

Expected: FAIL because the existing dialog uses the mock scan contract.

- [ ] **Step 3: Align frontend types with the platform API**

Use lowercase backend states and version status directly. Registration sends `source_root_id`, `relative_path`, categories, split ratios, analysis fingerprint, and a `crypto.randomUUID()` idempotency key. Poll `/api/jobs/{id}` every two seconds only while a job is pending/running and stop polling on unmount or terminal state.

Show the analysis table before submission: detected format, task type, image/annotation counts, categories, split counts, unsupported files, and errors. Job progress uses server-provided stage and processed/total values. Detail tabs load versions/items/categories from real endpoints and show an explicit unavailable/error state rather than mock fallback data.

- [ ] **Step 4: Run complete frontend verification and commit**

Run: `cd web && npm run test:run && npm run typecheck && npm run build`

Expected: PASS with no React act warnings, TypeScript errors, or build errors.

```bash
git add web
git commit -m "feat: connect dataset management frontend"
```

## Task 12: Add a Real Database/Redis Integration Test and Local Runtime

**Files:**
- Create: `.env.example`
- Create: `compose.yaml`
- Create: `deploy/api.Dockerfile`
- Create: `deploy/web.Dockerfile`
- Create: `deploy/nginx.dev.conf`
- Create: `tests/integration/test_register_dataset.py`
- Create: `tests/integration/fixtures.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing ten-image integration test**

```python
def test_registers_ten_images_into_ready_v1(integration_client, source_root, image_factory):
    for index in range(10):
        image_factory(source_root / "incoming" / f"image-{index:02d}.jpg", size=(64, 48))

    analysis = wait_for_job(
        integration_client,
        integration_client.post("/api/datasets/analyze", json=analysis_payload()).json()["job_id"],
    )
    response = integration_client.post(
        "/api/datasets/register",
        json=registration_payload(analysis["result"]["fingerprint"]),
    )
    job = wait_for_job(integration_client, response.json()["job_id"])
    dataset = integration_client.get(f"/api/datasets/{job['business_object_id']}").json()

    assert job["status"] == "succeeded"
    assert dataset["current_version"]["version_number"] == 1
    assert dataset["current_version"]["item_count"] == 10
    assert dataset["current_version"]["manifest"]["format"] == "platform-coco-v1"
```

- [ ] **Step 2: Run against Compose and verify services are not yet defined**

Run: `docker compose up -d postgres redis && uv run pytest -m integration tests/integration/test_register_dataset.py -v`

Expected: FAIL before implementation because Compose service definitions are missing.

- [ ] **Step 3: Implement the local runtime**

Compose defines PostgreSQL 16, Redis 7, API, one RQ worker, web, and development Nginx. Mount `./var/sources` read-only into API/worker at `/data/sources` and `./var/managed` read-write at `/data/managed`. Add health checks and make API/worker depend on healthy PostgreSQL/Redis. Do not add Label Studio or UnitTrain services in this phase.

`.env.example` contains non-secret development values and documents required production overrides. `README.md` gives exact `uv sync`, migration, admin creation, frontend install, Compose, and test commands, plus the known limitation that the local UniTrain environment is intentionally not required.

- [ ] **Step 4: Run full phase verification**

Run:

```bash
uv run pytest -m "not integration" -v
docker compose up -d postgres redis
uv run pytest -m integration tests/integration/test_register_dataset.py -v
uv run ruff check label_platform tests
uv run mypy label_platform
cd web && npm run test:run && npm run typecheck && npm run build
docker compose config --quiet
```

Expected: every command exits 0; the integration test publishes one ready ten-image version and repeated registration with the same idempotency key does not duplicate it.

- [ ] **Step 5: Commit the phase runtime and documentation**

```bash
git add .env.example compose.yaml deploy tests/integration README.md
git commit -m "test: verify dataset registration vertical slice"
```

## Phase Acceptance Checklist

- [ ] Administrator can create accounts and approved roots; data engineers cannot administer them.
- [ ] Browser directory selection cannot escape an active approved root through traversal, symlinks, or special files.
- [ ] Raw images, COCO Detection, COCO Instance Segmentation, and Label Studio JSON/ZIP inputs are detected and normalized.
- [ ] Canonical COCO, split files, and manifest use the `platform-coco-v1` contract.
- [ ] Instance masks authoritatively derive bbox and area.
- [ ] Publication is atomic, immutable, traceable, and idempotent.
- [ ] Long operations execute through one background worker and expose domain progress.
- [ ] The supplied frontend uses real authentication and dataset APIs with no mock-data fallback.
- [ ] Unit, API, integration, lint, type-check, frontend-test, and frontend-build commands all pass with fresh output.

After this checklist passes, write the phase-2 Label Studio review plan against the concrete API/model contracts produced here. The phase-2 connector must use REST configuration/import/export operations compatible with Label Studio 1.13.1, retain raw exports, expose `/projects/<id>/data` deep links, and never modify Label Studio's SQLite database.
