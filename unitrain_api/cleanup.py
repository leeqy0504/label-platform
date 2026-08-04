from __future__ import annotations

import shutil
from datetime import datetime, timezone

from unitrain_api.config import UnitTrainAPISettings
from unitrain_api.schemas import RunStatus
from unitrain_api.store import RunStore


def cleanup_prepared_runs(
    settings: UnitTrainAPISettings,
    *,
    now: datetime | None = None,
) -> int:
    store = RunStore(settings.run_root)
    current = now or datetime.now(timezone.utc)
    removed = 0
    for record in store.list_runs():
        remove = record.status in {RunStatus.COMPLETED, RunStatus.STOPPED}
        if record.status is RunStatus.FAILED and record.completed_at is not None:
            age_hours = (current - record.completed_at).total_seconds() / 3600
            remove = age_hours >= settings.failed_prepared_retention_hours
        if not remove:
            continue
        prepared = store.run_dir(record.id) / "prepared"
        if prepared.is_symlink() or prepared.is_file():
            prepared.unlink(missing_ok=True)
            removed += 1
        elif prepared.is_dir():
            shutil.rmtree(prepared)
            removed += 1
    return removed
