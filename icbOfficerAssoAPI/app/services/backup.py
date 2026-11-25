"""Automatic database backups while the system runs.

A consistent copy of the SQLite file (SQLite's own online backup, so it is
safe while ballots are being saved) is written to `data/Backups`:

* once when the API starts and once when it stops,
* every BACKUP_INTERVAL_MINUTES while something changed since the last copy.

The newest BACKUP_KEEP copies are kept.  A copy is a complete database: to go
back to it, stop the system and put it in `data/` under the name of the
database file (icbOfficerAssoDB<year>.db).
"""

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.events import notifier

logger = logging.getLogger(__name__)


def _copy(source: Path, target_dir: Path, keep: int, reason: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = target_dir / f"{source.stem}_{stamp}_{reason}{source.suffix}"
    partial = target.with_suffix(".part")
    src = sqlite3.connect(source, timeout=30)
    try:
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if ok != "ok":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"the copy did not pass the integrity check: {ok}")
    partial.replace(target)

    copies = sorted(target_dir.glob(f"{source.stem}_*{source.suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in copies[max(keep, 1):]:
        old.unlink(missing_ok=True)
    return target


async def backup_now(reason: str = "manual") -> Path | None:
    """Write one backup copy now; None when there is nothing to copy or it failed (never raises)."""
    source = settings.database_file
    if source is None or not source.exists():
        return None
    try:
        target = await asyncio.to_thread(_copy, source, settings.backup_dir, settings.BACKUP_KEEP, reason)
        logger.info("Database backup written: %s", target)
        return target
    except Exception:
        logger.exception("Database backup failed")
        return None


async def backup_loop() -> None:
    """Background task: a copy every BACKUP_INTERVAL_MINUTES while the data changed."""
    interval = settings.BACKUP_INTERVAL_MINUTES * 60
    if interval <= 0:
        return
    seen = notifier.version
    while True:
        await asyncio.sleep(interval)
        if notifier.version == seen:
            continue
        seen = notifier.version
        await backup_now("auto")
