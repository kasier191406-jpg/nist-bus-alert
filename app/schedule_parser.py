from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable

from bs4 import BeautifulSoup


EMPTY_MARKERS = ("no record", "no schedule", "not available", "not published", "no data found", "schedule is not")
SCHEDULE_WORDS = ("bus", "route", "vehicle", "departure", "arrival", "pickup", "drop", "driver", "conductor")


@dataclass(frozen=True)
class Schedule:
    normalized: str
    display_lines: tuple[str, ...]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.normalized.encode("utf-8")).hexdigest()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_empty_text(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in EMPTY_MARKERS)


def _rows(table) -> list[list[str]]:
    result = []
    for tr in table.find_all("tr"):
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if cells:
            result.append(cells)
    return result


def _score_table(rows: list[list[str]]) -> int:
    flattened = " ".join(" ".join(row) for row in rows).lower()
    if _is_empty_text(flattened):
        return -100
    header = " ".join(rows[0]).lower() if rows else ""
    header_score = sum(word in header for word in SCHEDULE_WORDS) * 10
    data_rows = [row for row in rows[1:] if len(row) >= 2 and not _is_empty_text(" ".join(row))]
    return header_score + len(data_rows) * 2


def _canonical_rows(rows: Iterable[list[str]]) -> tuple[str, tuple[str, ...]]:
    cleaned = []
    for row in rows:
        values = [_clean(value) for value in row if _clean(value)]
        if len(values) >= 2 and not _is_empty_text(" ".join(values)):
            cleaned.append(values)
    # Keep column and row meaning, while ignoring incidental whitespace and formatting.
    normalized = "\n".join(" | ".join(value.casefold() for value in row) for row in cleaned)
    display = tuple(" | ".join(row) for row in cleaned)
    return normalized, display


def parse_schedule(html: str) -> Schedule | None:
    """Return a schedule only when a plausible populated schedule table exists.

    The ERP may return a successful HTML page before publishing a schedule, so this
    deliberately requires schedule-like table headers and at least one data row.
    """
    if not html or _is_empty_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True)):
        return None

    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for table in soup.find_all("table"):
        table_rows = _rows(table)
        if len(table_rows) < 2:
            continue
        score = _score_table(table_rows)
        header = " ".join(table_rows[0]).lower()
        data_rows = table_rows[1:]
        # Requiring a domain header avoids treating an unrelated status/layout table as a schedule.
        if score >= 12 and any(word in header for word in SCHEDULE_WORDS):
            candidates.append((score, table_rows[0], data_rows))

    if not candidates:
        return None
    _, header, data_rows = max(candidates, key=lambda candidate: candidate[0])
    normalized, display = _canonical_rows([header, *data_rows])
    if not display or len(display) < 2:
        return None
    return Schedule(normalized=normalized, display_lines=display)
