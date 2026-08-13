"""Stream Odoo log files and turn matching lines into rows."""

from __future__ import annotations

import calendar
import gzip
import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any

from odoo_logs import patterns

LOG_TIME = "%Y-%m-%d %H:%M:%S,%f"
ERROR_LEVELS = ("ERROR", "CRITICAL")

AGO_RE = re.compile(r"^(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$")
SPAN_RE = re.compile(r"^(this|last)\s+(week|month|year)$")
_DELTAS = {"minute": "minutes", "hour": "hours", "day": "days", "week": "weeks"}


def open_log(path: Path) -> IO[str]:
    """Rotated logs are gzipped, and any log can carry undecodable bytes."""
    opener = gzip.open if path.suffix == ".gz" else open

    return opener(path, "rt", encoding="utf-8", errors="replace")


def parse_time(raw: str) -> datetime:
    return datetime.strptime(raw, LOG_TIME)


def parse_bound(raw: str | None) -> datetime | None:
    """Accept a bare date or a full timestamp on --from / --to."""
    if not raw:
        return None

    for fmt in (LOG_TIME, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    message = f"unrecognized date: {raw!r} (use YYYY-MM-DD[ HH:MM:SS])"
    raise ValueError(message)


def parse_period(raw: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """emoi's `--period`: a human range, as a pair of bounds.

    Same grammar emoi documents, off the standard library rather than
    `dateparser` — anything outside it is refused rather than guessed at.
    """
    raw = " ".join(raw.lower().split())
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if raw in ("today", "yesterday"):
        day = today if raw == "today" else today - timedelta(days=1)
        return day, _end_of(day)

    if found := AGO_RE.match(raw):
        return _shift(now, -int(found[1]), found[2]), now

    if found := SPAN_RE.match(raw):
        start = _start_of(today, found[2])
        if found[1] == "this":
            return start, now

        # The previous period runs up to the moment this one starts.
        return _shift(start, -1, found[2]), _end_of(start - timedelta(days=1))

    message = f"unrecognized period: {raw!r} (use today, yesterday, '<n> days ago', 'this week', 'last month')"
    raise ValueError(message)


def _end_of(day: datetime) -> datetime:
    return day.replace(hour=23, minute=59, second=59, microsecond=999999)


def _start_of(day: datetime, unit: str) -> datetime:
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)

    return day.replace(month=1, day=1)


def _shift(when: datetime, count: int, unit: str) -> datetime:
    if unit in _DELTAS:
        return when + timedelta(**{_DELTAS[unit]: count})

    months = when.year * 12 + when.month - 1 + count * (12 if unit == "year" else 1)
    year, month = divmod(months, 12)
    # 31 March a month back is the 28th, not the 3rd.
    day = min(when.day, calendar.monthrange(year, month + 1)[1])

    return when.replace(year=year, month=month + 1, day=day)


def _enrich(row: dict[str, Any]) -> dict[str, Any]:
    """Pull fields the head can't carry out of the message itself."""
    event = row.get("event") or row.get("message") or ""

    if alt_db := row.pop("alt_db", None) or _search(patterns.ALT_DB_RE, event, "alt_db"):
        row["db"] = alt_db

    if not row.get("duration"):
        row["duration"] = _search(patterns.DURATION_RE, event, "duration")

    if not row.get("job"):
        found = patterns.UUID_RE.search(event)
        row["job"] = found.group(0) if found else None

    if "route" in row:
        row["model"], row["method"], row["endpoint"] = describe_route(row["route"])
        row["total"] = None

        # Odoo appends `query_count query_time remaining_time` from 12.0 on;
        # before that werkzeug's line stops after the status.
        if row["query_time"] is not None:
            row["queries"] = int(row["queries"])
            row["query_time"] = float(row["query_time"])
            row["other_time"] = float(row["other_time"])
            row["total"] = round(row["query_time"] + row["other_time"], 3)

    return row


def describe_route(route: str) -> tuple[str | None, str | None, str]:
    """Reduce a route to one grouping key, plus model+method where they're real.

    `/web/dataset/call_kw/res.partner/web_read` is the only shape whose tail
    is genuinely a model and a method; it keys as `res.partner.web_read`.
    Anything else keys on the path with record ids collapsed, so
    `/web/image/42/description/icon.png` doesn't split per record.
    """
    path = route.split("?")[0]

    if matched := patterns.CALL_KW_RE.search(path):
        model, method = matched["model"], matched["method"]
        return model, method, f"{model}.{method}"

    return None, None, patterns.ROUTE_ID_RE.sub("/N", path.rstrip("/")) or "/"


def classify_route(route: str) -> str:
    """Which kind of traffic a request is — `usage`'s grouping key."""
    path = route.split("?")[0]

    for name, regex in patterns.USAGE_CLASSES:
        if regex.match(path):
            return name

    return "other"


def _search(regex, text: str, group: str) -> str | None:
    found = regex.search(text)

    return found.group(group) if found else None


def _keep(
    row: dict[str, Any],
    since: datetime | None,
    until: datetime | None,
    database: str | None,
) -> bool:
    if since and row["time"] < since:
        return False
    if until and row["time"] > until:
        return False

    return not database or row.get("db") == database


def scan(
    name: str,
    paths: Iterable[Path],
    since: datetime | None = None,
    until: datetime | None = None,
    database: str | None = None,
    source: bool = False,
) -> list[dict[str, Any]]:
    """Every line of every file matched against one command's patterns.

    `source` keeps the log line each row came from. Off by default because a
    busy log matches millions of lines and the text dwarfs the fields.
    """
    regexes = patterns.PATTERNS[name]
    rows: list[dict[str, Any]] = []

    for path in paths:
        with open_log(path) as fh:
            for line in fh:
                # 80%+ of lines are traceback continuations no command can
                # match. Every pattern starts with HEAD, so one head match
                # rejects them all — see test_every_pattern_starts_with_head.
                if not patterns.HEAD_RE.match(line):
                    continue

                for regex in regexes:
                    matched = regex.match(line)
                    if not matched:
                        continue

                    row = matched.groupdict()
                    for key in patterns.FIELDS[name]:
                        row.setdefault(key, None)

                    row = _enrich(row)
                    row["time"] = parse_time(row["time"])
                    row["path"] = str(path)
                    if source:
                        row["source"] = line
                    if _keep(row, since, until, database):
                        rows.append(row)

                    break

    # buffered so multiple rotated files come out in time order;
    # stream with a heap merge if a command ever returns millions of rows.
    rows.sort(key=lambda row: row["time"])

    return rows


def blocks(
    paths: Iterable[Path],
    since: datetime | None = None,
    until: datetime | None = None,
    database: str | None = None,
) -> Iterator[dict[str, Any]]:
    """ERROR/CRITICAL entries with their traceback, one dict per entry."""
    for row in _blocks(paths):
        if _keep(row, since, until, database):
            yield row


def _blocks(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """A log entry runs from a timestamped head line to the next one, so the
    traceback below an error belongs to it."""
    for path in paths:
        with open_log(path) as fh:
            head, body = None, []

            for line in fh:
                matched = patterns.HEAD_RE.match(line)
                if not matched:
                    if head is not None:
                        body.append(line)
                    continue

                if head is not None:
                    yield _block(head, body, path)

                head = matched if matched["level"] in ERROR_LEVELS else None
                body = [line] if head is not None else []

            if head is not None:
                yield _block(head, body, path)


def _block(matched, body: list[str], path: Path) -> dict[str, Any]:
    row = _enrich(matched.groupdict())
    row["time"] = parse_time(row["time"])
    row["path"] = str(path)
    row["text"] = "".join(body)

    # The last exception line wins: chained tracebacks put the raised one last.
    row["type"], row["error"] = row["logger"], row["message"]
    for line in reversed(body):
        found = patterns.EXCEPTION_RE.match(line.rstrip())
        if found:
            row["type"] = found["type"]
            row["error"] = found["error"] or ""
            break

    return row
