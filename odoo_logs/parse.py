"""Stream Odoo log files and turn matching lines into rows."""

from __future__ import annotations

import calendar
import gzip
import json
import os
import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import IO, Any

from odoo_logs import patterns

LOG_TIME = "%Y-%m-%d %H:%M:%S,%f"
ERROR_LEVELS = ("ERROR", "CRITICAL")

# Each --from/--to format with the unit it leaves open on its right.
_BOUND_FMTS = (
    (LOG_TIME, None),
    ("%Y-%m-%d %H:%M:%S", "second"),
    ("%Y-%m-%d %H:%M", "minute"),
    ("%Y-%m-%d", "day"),
)

AGO_RE = re.compile(r"^(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$")
SPAN_RE = re.compile(r"^(this|last)\s+(week|month|year)$")
_DELTAS = {"minute": "minutes", "hour": "hours", "day": "days", "week": "weeks"}


def open_log(path: Path) -> IO[str]:
    """Rotated logs are gzipped, and any log can carry undecodable bytes."""
    opener = gzip.open if path.suffix == ".gz" else open

    return opener(path, "rt", encoding="utf-8", errors="replace")


# `2026-09-25 19:50:18,449`: what every entry head starts with.
STAMP_LEN = len("2026-09-25 19:50:18,449")
TAIL_CHUNK = 64 * 1024
# A log directory also holds lock files and the like: `server.log`,
# `server.log.2026-09-25`, `server.log.1.gz` and `odoo-2026-09-25.log` are
# logs, `server.log_rotating_lock` is not.
LOG_NAME_RE = re.compile(r"\.log($|[.\-])")


def collect(paths: Iterable[Path]) -> list[Path]:
    """Expand what `list` is handed into the log files it names.

    A directory yields its logs. A base `*.log` also yields its rotated
    siblings (`server.log.*` and dated `server.log-*`), so `server.log` stands
    for the whole rotation;
    any other file stands for itself.
    """
    found: list[Path] = []

    for path in paths:
        if path.is_dir():
            found.extend(sorted(p for p in path.iterdir() if p.is_file() and LOG_NAME_RE.search(p.name)))
            continue

        found.append(path)
        if path.suffix == ".log":
            # `server.log.1`, and logrotate's dateext `server.log-2026-09-29-<epoch>.gz`.
            found.extend(sorted([*path.parent.glob(f"{path.name}.*"), *path.parent.glob(f"{path.name}-*")]))

    return list(dict.fromkeys(found))


def _stamped(line: bytes) -> bool:
    """Cheap test for an entry head: traceback lines never start like this."""
    return len(line) >= STAMP_LEN and line[4:5] == b"-" and line[:4].isdigit()


def _stamp(line: bytes | None) -> datetime | None:
    if line is None:
        return None

    try:
        return datetime.strptime(line[:STAMP_LEN].decode("ascii"), LOG_TIME)
    except (ValueError, UnicodeDecodeError):
        return None


def _head_tail_plain(path: Path) -> tuple[bytes | None, bytes | None]:
    """First and last entry head of a plain file, reading only its two ends."""
    with path.open("rb") as fh:
        first = next((line for line in fh if _stamped(line)), None)
        if first is None:
            return None, None

        position = fh.seek(0, 2)
        held = b""

        while position > 0:
            step = min(TAIL_CHUNK, position)
            position -= step
            fh.seek(position)
            lines = (fh.read(step) + held).split(b"\n")

            # Unless this chunk starts the file, its first line is cut off.
            held = lines[0] if position else b""
            for line in reversed(lines[1:] if position else lines):
                if _stamped(line):
                    return first, line

    return first, first


def _head_tail_gzip(path: Path) -> tuple[bytes | None, bytes | None, bool]:
    """A gzip stream can't be read from the end, so it is inflated once.

    Memory stays at one line. A truncated archive (a rotation interrupted
    mid-write) still yields everything before the break.
    """
    first = last = None
    complete = True

    try:
        with gzip.open(path, "rb") as fh:
            for line in fh:
                if _stamped(line):
                    first = first or line
                    last = line
    except (OSError, EOFError):
        complete = False

    return first, last, complete


def _cache_file() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "odoo-logs" / "periods.json"


def _load_cache() -> dict[str, Any]:
    try:
        found = json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return {}

    return found if isinstance(found, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Best effort: a cache that can't be written costs a re-read, not a failure."""
    cache = {key: value for key, value in cache.items() if os.path.exists(key.rsplit("|", 2)[0])}

    try:
        target = _cache_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_suffix(f".{os.getpid()}.tmp")
        scratch.write_text(json.dumps(cache))
        scratch.replace(target)
    except OSError:
        pass


def _gzip_period(path: Path, cache: dict[str, Any]) -> tuple[datetime | None, datetime | None, bool]:
    """A rotated archive never changes, so what inflating it taught is kept,
    keyed by the file's size and mtime: a rewritten archive misses on its own."""
    stat = path.stat()
    key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"

    if key in cache:
        start, end, complete = cache[key]
        return (
            datetime.fromisoformat(start) if start else None,
            datetime.fromisoformat(end) if end else None,
            complete,
        )

    first, last, complete = _head_tail_gzip(path)
    start, end = _stamp(first), _stamp(last)
    cache[key] = [start and start.isoformat(), end and end.isoformat(), complete]

    return start, end, complete


def describe(path: Path, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """One row of `list`: what a log file is and what period it covers."""
    notes: list[str] = []

    if path.suffix == ".gz":
        notes.append("gz")
        start, end, complete = _gzip_period(path, {} if cache is None else cache)
        if not complete:
            notes.append("truncated")
    else:
        first, last = _head_tail_plain(path)
        start, end = _stamp(first), _stamp(last)

    if start is None:
        notes.append("empty" if path.stat().st_size == 0 else "no timestamps")

    return {"path": str(path), "size": path.stat().st_size, "start": start, "end": end, "note": ", ".join(notes)}


def survey(
    paths: Iterable[Path],
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Every log file under `paths` with its period, oldest first.

    Files outside --from/--to are dropped, so what is left is exactly the
    set a scan of that window would have to read. A file whose period can't
    be read is kept: nothing says it is outside.
    """
    cache = _load_cache()
    files = []
    for path in collect(paths):
        before = dict(cache)
        files.append(describe(path, cache))
        # Save as soon as a describe() taught the cache something, so an
        # interrupted run (Ctrl-C, a caller's CPU-time limit) keeps the
        # archives it already inflated instead of losing them to the next
        # run. The cache is a few KB; the extra writes are nothing next to
        # inflating one.
        if cache != before:
            _save_cache(cache)

    files.sort(key=lambda row: (row["start"] is None, row["start"] or datetime.min, row["path"]))

    # Rotation hands each file the period after the last one; when it
    # doesn't, a window may be read twice or not at all.
    reach = None
    for row in files:
        if reach and row["start"] and row["start"] < reach:
            row["note"] = ", ".join(filter(None, [row["note"], "overlaps previous"]))
        if row["end"]:
            reach = max(reach or row["end"], row["end"])

    return [row for row in files if _within(row, since, until)]


def _within(row: dict[str, Any], since: datetime | None, until: datetime | None) -> bool:
    if since and row["end"] and row["end"] < since:
        return False

    return not (until and row["start"] and row["start"] > until)


def parse_time(raw: str) -> datetime:
    return datetime.strptime(raw, LOG_TIME)


def parse_bound(raw: str | None, end: bool = False) -> datetime | None:
    """Accept a bare date or a full timestamp on --from / --to.

    --to is an inclusive upper bound, so `end` rounds up to the last instant
    the written precision covers: `-t 2026-08-13` asks for the whole 13th.
    """
    if not raw:
        return None

    for fmt, unit in _BOUND_FMTS:
        try:
            found = datetime.strptime(raw, fmt)
        except ValueError:
            continue

        return _round_up(found, unit) if end and unit else found

    message = f"unrecognized date: {raw!r} (use YYYY-MM-DD[ HH:MM:SS])"
    raise ValueError(message)


def _round_up(when: datetime, unit: str) -> datetime:
    if unit == "day":
        return _end_of(when)
    if unit == "minute":
        return when.replace(second=59, microsecond=999999)

    # Odoo timestamps carry milliseconds; a bound written to the second has
    # to cover them or it drops the very second it names.
    return when.replace(microsecond=999999)


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

    if "data" in row:
        unfolded = patterns.MAIL_FOLD_RE.sub(" ", row.pop("data"))
        row["mail_from"] = _unescape(_search(patterns.MAIL_FROM_RE, unfolded, "value"))
        row["mail_to"] = _unescape(_search(patterns.MAIL_TO_RE, unfolded, "value"))
        row["subject"] = _decode_subject(_unescape(_search(patterns.MAIL_SUBJECT_RE, unfolded, "value")))
        row["message_id"] = _unescape(_search(patterns.MAIL_MESSAGE_ID_RE, unfolded, "value"))

    # An SMTP reply is `repr(bytes)` like the DATA payload above.
    if row.get("code"):
        row["error"] = _unescape(row["error"])

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


def _decode_subject(subject: str | None) -> str | None:
    """RFC 2047: a non-ASCII subject rides as `=?utf-8?q?...?=` words mixed
    into otherwise plain text; decode each back to the character it names."""
    if not subject:
        return subject

    try:
        return "".join(
            chunk.decode(encoding or "ascii", errors="replace") if isinstance(chunk, bytes) else chunk
            for chunk, encoding in decode_header(subject)
        )
    except (ValueError, LookupError):
        return subject


def _unescape(value: str | None) -> str | None:
    """The DATA payload is `repr(bytes)`, so `'` rides as `\\'`. Undo quote
    and backslash escapes only — `\\r`/`\\n` stay as-is: the fold regex and
    header patterns still match on the two-character sequences."""
    if not value:
        return value

    return re.sub(r"\\(['\"\\])", r"\1", value)


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

    # A line with no db can't be shown to belong elsewhere, so -d keeps it.
    return not database or row.get("db") in (database, *patterns.UNKNOWN_DBS)


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
