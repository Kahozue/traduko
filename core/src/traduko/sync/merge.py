"""Row-level three-way merge for glossary CSV files (design doc section 9).

Rows are keyed by the source term and compared as whole rows against the
base version from the last successful sync. Only a term edited on both
sides to different values is a conflict; the merged file keeps the local
row and the conflict is surfaced for a human decision. Deletions never
propagate in v1: a row missing on one side is restored from the other.
"""
from __future__ import annotations

import csv
import io

FIELDS = ("source", "target", "notes", "category")

Row = dict[str, str]


def parse_rows(text: str) -> dict[str, Row]:
    rows: dict[str, Row] = {}
    for raw in csv.DictReader(io.StringIO(text)):
        source = (raw.get("source") or "").strip()
        if not source:
            continue
        rows[source] = {
            field: (raw.get(field) or "").strip() for field in FIELDS
        }
    return rows


def render_rows(rows: dict[str, Row]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for source in sorted(rows):
        writer.writerow(rows[source])
    return out.getvalue()


def merge_glossary(
    base_text: str, local_text: str, remote_text: str
) -> tuple[str, list[dict]]:
    base = parse_rows(base_text)
    local = parse_rows(local_text)
    remote = parse_rows(remote_text)

    merged: dict[str, Row] = {}
    conflicts: list[dict] = []
    for source in sorted(set(base) | set(local) | set(remote)):
        base_row = base.get(source)
        local_row = local.get(source)
        remote_row = remote.get(source)
        if local_row is None or remote_row is None:
            # Present on one side only: addition or deletion. Either way the
            # existing row wins because deletions do not propagate.
            row = local_row or remote_row
            if row is not None:
                merged[source] = row
            continue
        if local_row == remote_row:
            merged[source] = local_row
        elif remote_row == base_row:
            merged[source] = local_row
        elif local_row == base_row:
            merged[source] = remote_row
        else:
            merged[source] = local_row
            conflicts.append(
                {"source": source, "local": local_row, "remote": remote_row}
            )
    return render_rows(merged), conflicts
