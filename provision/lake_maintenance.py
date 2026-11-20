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

The bronze table ``raw_responses`` (burndown 17.5) gets the same pass, by its
``received_at`` day, after first deleting days older than its retention
(``RAW_RETENTION_DAYS``, default 30): bronze is for rebuilding and citing sources,
not history. A whole-day delete on a day-partitioned table removes files without
rewriting any.

Run with ``python provision/horus.py maintain-lake`` (a plan) or ``--yes``; the
provisioner schedules it daily as a Workbench Job.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

# Iceberg and Trino's usual target. A day of Horus data is a few hundred MB, so a
# compacted day is a handful of files.
TARGET_FILE_BYTES = 128 * 1024 * 1024
# A day is compacted when it has more than this many times the files its size needs.
SLACK = 2
RETENTION = "7d"
RAW_RETENTION_DAYS = 30


def partitions(run: Callable[[str], list], fq: str, time_col: str = "event_time",
               target: int = TARGET_FILE_BYTES) -> List[Tuple[Optional[str], int, int, int, int]]:
    """(day, file_count, total_bytes, records, files_needed) per day, oldest first. A
    table also partitioned by another column (raw_responses: by flow) is summed per
    day; files_needed is then summed per partition, since files never span two."""
    catalog_db, table = fq.rsplit(".", 1)
    rows = run(f'SELECT CAST(partition.{time_col}_day AS VARCHAR), file_count, total_size, record_count '
               f'FROM {catalog_db}."{table}$partitions"')
    days: dict = {}
    for r in rows:
        d = days.setdefault(r[0], [0, 0, 0, 0])
        d[0] += int(r[1]); d[1] += int(r[2]); d[2] += int(r[3])
        d[3] += files_needed(int(r[2]), target)
    return sorted(((k, *v) for k, v in days.items()), key=lambda r: (r[0] is None, r[0] or ""))


def files_needed(total_bytes: int, target: int = TARGET_FILE_BYTES) -> int:
    return max(1, math.ceil(total_bytes / target))


def plan(parts, today: str) -> List[str]:
    """The finished days worth compacting."""
    return [day for day, files, _size, _rows, needed in parts
            if day is not None and day < today and files > SLACK * needed]


def compact(run: Callable[[str], list], fq: str, day: str, time_col: str = "event_time") -> None:
    run(f"ALTER TABLE {fq} EXECUTE optimize "
        f"WHERE {time_col} >= TIMESTAMP '{day} 00:00:00' "
        f"AND {time_col} < TIMESTAMP '{day} 00:00:00' + INTERVAL '1' DAY")


def expired_days(parts, today: str, retain_days: int) -> List[str]:
    """Days older than the retention: today minus ``retain_days`` is the oldest kept."""
    cutoff = (date.fromisoformat(today) - timedelta(days=retain_days)).isoformat()
    return [day for day, *_ in parts if day is not None and day < cutoff]


def maintain(run: Callable[[str], list], fq: str, apply: bool, log=print,
             today: Optional[str] = None, target: int = TARGET_FILE_BYTES,
             time_col: str = "event_time", retain_days: Optional[int] = None) -> dict:
    """One maintenance pass. Without ``apply``, only reports what it would do.
    ``retain_days``: delete whole days older than this first (bronze only)."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = partitions(run, fq, time_col, target)
    dropped: List[str] = []
    if retain_days is not None:
        dropped = expired_days(parts, today, retain_days)
        cutoff = (date.fromisoformat(today) - timedelta(days=retain_days)).isoformat()
        log(f"lake maintenance: {fq}: keep {retain_days} days; {len(dropped)} older day(s) to delete"
            + (f": {dropped[0]} to {dropped[-1]}" if dropped else ""))
        if apply and dropped:
            run(f"DELETE FROM {fq} WHERE {time_col} < TIMESTAMP '{cutoff} 00:00:00'")
            parts = partitions(run, fq, time_col, target)
        elif dropped:
            parts = [p for p in parts if p[0] not in dropped]
    days = plan(parts, today)
    total_files = sum(p[1] for p in parts)
    log(f"lake maintenance: {fq}: {len(parts)} days, {total_files} files; "
        f"{len(days)} finished day(s) to compact" + (f": {', '.join(days)}" if days else ""))
    for day, files, size, records, needed in parts:
        if day in days:
            log(f"  {day}: {files} files, {size / 1e6:.0f} MB, {records} rows -> about {needed}")
    if not apply:
        log(f"  then expire snapshots and remove orphan files older than {RETENTION}")
        return {"days": days, "dropped": dropped, "files_before": total_files}
    for day in days:
        compact(run, fq, day, time_col)
        after = next((p[1] for p in partitions(run, fq, time_col, target) if p[0] == day), None)
        log(f"lake maintenance: {day} compacted to {after} files")
    run(f"ALTER TABLE {fq} EXECUTE expire_snapshots(retention_threshold => '{RETENTION}')")
    run(f"ALTER TABLE {fq} EXECUTE remove_orphan_files(retention_threshold => '{RETENTION}')")
    files_after = sum(p[1] for p in partitions(run, fq, time_col, target))
    log(f"lake maintenance: done; {total_files} -> {files_after} files; "
        f"snapshots and orphan files older than {RETENTION} removed")
    return {"days": days, "dropped": dropped, "files_before": total_files, "files_after": files_after}
