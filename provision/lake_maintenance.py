"""Daily maintenance of the events table (burndown 16.6), through Trino.

The Flink job commits a few small files on every checkpoint (about 1,300 a day)
in arrival order. Maintenance, for each finished day:

1. **Compact** a day that has many more files than its size needs into files of
   about ``iceberg.target-max-file-size``, written in the table's sort order
   (``tile_z8``, then ``event_time``), so each file covers a small area and a
   bounding-box query reads few files. Today is left alone: Flink is still
   writing it.
2. **Expire snapshots** older than ``RETENTION`` (Trino's minimum is 7 days by
   default), so replaced files can be deleted.
3. **Remove orphan files** older than ``RETENTION``: files no snapshot uses, such
   as those left by a failed write.

Run with ``python provision/horus.py maintain-lake`` (a plan) or ``--yes``; the
provisioner schedules it daily as a Workbench Job.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

# Iceberg and Trino's usual target. A day of Horus data is a few hundred MB, so a
# compacted day is a handful of files.
TARGET_FILE_BYTES = 128 * 1024 * 1024
# A day is compacted when it has more than this many times the files its size needs.
SLACK = 2
RETENTION = "7d"


def partitions(run: Callable[[str], list], fq: str) -> List[Tuple[Optional[str], int, int, int]]:
    """(day, file_count, total_bytes, records) per day partition, oldest first."""
    catalog_db, table = fq.rsplit(".", 1)
    rows = run(f'SELECT CAST(partition.event_time_day AS VARCHAR), file_count, total_size, record_count '
               f'FROM {catalog_db}."{table}$partitions"')
    return sorted(((r[0], int(r[1]), int(r[2]), int(r[3])) for r in rows), key=lambda r: (r[0] is None, r[0] or ""))


def files_needed(total_bytes: int, target: int = TARGET_FILE_BYTES) -> int:
    return max(1, math.ceil(total_bytes / target))


def plan(parts, today: str, target: int = TARGET_FILE_BYTES) -> List[str]:
    """The finished days worth compacting."""
    return [day for day, files, size, _ in parts
            if day is not None and day < today and files > SLACK * files_needed(size, target)]


def compact(run: Callable[[str], list], fq: str, day: str) -> None:
    run(f"ALTER TABLE {fq} EXECUTE optimize "
        f"WHERE event_time >= TIMESTAMP '{day} 00:00:00' "
        f"AND event_time < TIMESTAMP '{day} 00:00:00' + INTERVAL '1' DAY")


def maintain(run: Callable[[str], list], fq: str, apply: bool, log=print,
             today: Optional[str] = None, target: int = TARGET_FILE_BYTES) -> dict:
    """One maintenance pass. Without ``apply``, only reports what it would do."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = partitions(run, fq)
    days = plan(parts, today, target)
    total_files = sum(p[1] for p in parts)
    log(f"lake maintenance: {fq}: {len(parts)} days, {total_files} files; "
        f"{len(days)} finished day(s) to compact" + (f": {', '.join(days)}" if days else ""))
    for day, files, size, records in parts:
        if day in days:
            log(f"  {day}: {files} files, {size / 1e6:.0f} MB, {records} rows -> about {files_needed(size, target)}")
    if not apply:
        log(f"  then expire snapshots and remove orphan files older than {RETENTION}")
        return {"days": days, "files_before": total_files}
    for day in days:
        compact(run, fq, day)
        after = next((p[1] for p in partitions(run, fq) if p[0] == day), None)
        log(f"lake maintenance: {day} compacted to {after} files")
    run(f"ALTER TABLE {fq} EXECUTE expire_snapshots(retention_threshold => '{RETENTION}')")
    run(f"ALTER TABLE {fq} EXECUTE remove_orphan_files(retention_threshold => '{RETENTION}')")
    files_after = sum(p[1] for p in partitions(run, fq))
    log(f"lake maintenance: done; {total_files} -> {files_after} files; "
        f"snapshots and orphan files older than {RETENTION} removed")
    return {"days": days, "files_before": total_files, "files_after": files_after}
