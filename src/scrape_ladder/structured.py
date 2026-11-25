"""Structured parse for CSV, JSON and XLSX responses."""
from __future__ import annotations

import csv
import io
import json
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

SAMPLE_ROWS = 5
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class StructuredParse(BaseModel):
    format: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)


def kind_of(url: str, content_type: str) -> str | None:
    """'csv', 'json' or 'xlsx' when the response is one of those, else None."""
    media = content_type.split(";", 1)[0].strip().lower()
    suffix = PurePosixPath(urlsplit(url).path.lower()).suffix
    if media in {"text/csv", "application/csv"} or suffix == ".csv":
        return "csv"
    if media == _XLSX_TYPE or suffix == ".xlsx":
        return "xlsx"
    if media in {"application/json", "application/geo+json"} or media.endswith("+json") or suffix == ".json":
        return "json"
    return None


def parse(body: bytes, kind: str) -> StructuredParse:
    if kind == "csv":
        return _csv(body)
    if kind == "json":
        return _json(body)
    if kind == "xlsx":
        return _xlsx(body)
    raise ValueError(f"unknown structured kind: {kind}")


def _csv(body: bytes) -> StructuredParse:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="replace"), newline=""))
    rows = list(reader)
    return StructuredParse(format="csv", row_count=len(rows), columns=list(reader.fieldnames or []),
                           sample_rows=rows[:SAMPLE_ROWS])


def _json(body: bytes) -> StructuredParse:
    value = json.loads(body.decode("utf-8-sig", errors="replace"))
    rows: list[Any]
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        found = next((value[k] for k in ("data", "results", "items", "records") if isinstance(value.get(k), list)), None)
        rows = found if found is not None else [value]
    else:
        rows = [value]
    rows = [r if isinstance(r, dict) else {"value": r} for r in rows]
    columns = sorted({key for row in rows[:25] for key in row})
    return StructuredParse(format="json", row_count=len(rows), columns=columns, sample_rows=rows[:SAMPLE_ROWS])


def _xlsx(body: bytes) -> StructuredParse:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        sheet = book.worksheets[0]
        values = [list(r) for r in sheet.iter_rows(values_only=True)]
    finally:
        book.close()
    values = [r for r in values if any(c is not None for c in r)]
    if not values:
        return StructuredParse(format="xlsx", row_count=0)
    header = [str(c) if c is not None else f"column_{i + 1}" for i, c in enumerate(values[0])]
    rows = [dict(zip(header, r)) for r in values[1:]]
    return StructuredParse(format="xlsx", row_count=len(rows), columns=header, sample_rows=rows[:SAMPLE_ROWS])
