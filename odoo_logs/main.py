from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from importlib.metadata import version as pkg_version
from pathlib import Path
from statistics import mean, median
from typing import Annotated, Any

import typer

from odoo_logs import output, parse, patterns

app = typer.Typer(no_args_is_help=True, help="Prefiltered data out of Odoo server logs.")

LOGS = Annotated[
    list[Path],
    typer.Argument(
        metavar="LOGS...",
        exists=True,
        dir_okay=False,
        help="Log files to read; plain or gzipped (server.log server.log.*.gz).",
    ),
]
LIMIT = Annotated[int, typer.Option("--limit", "-n", help="Max rows; 0 for all.")]

# A scan with no --period/--from/--to reads the whole of every file given.
# That is the right default — nothing can be hidden from a file you named —
# but past this many rows it is worth saying which span you just read.
NUDGE_ROWS = 1000

AGGREGATES = ("hour", "day", "week", "month")
AGGREGATE = Annotated[
    str | None,
    typer.Option("--aggregate", "-a", help=f"Bucket the stats by period: {', '.join(AGGREGATES)}."),
]

# Timestamps and period labels are fixed width; folding them across lines just
# costs height.
TIMES = {"time", "first", "last", "period"}

_output_file: str | None = None
_output_format: str = "text"
_since: datetime | None = None
_until: datetime | None = None
_database: str | None = None
_verbose: str | None = None
_bounded: bool = False


def version_callback(value: bool):
    if value:
        typer.echo(f"odoo-logs {pkg_version('odoo-logs')}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = False,
    output_file: Annotated[str, typer.Option("--output-file")] = "-",
    output_format: Annotated[
        str, typer.Option("--output-format", help=f"One of: {', '.join(output.FORMATS)}.")
    ] = "text",
    from_: Annotated[
        str | None,
        typer.Option("--from", "-f", help="Only entries at or after YYYY-MM-DD[ HH:MM:SS]."),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", "-t", help="Only entries at or before YYYY-MM-DD[ HH:MM:SS]."),
    ] = None,
    period: Annotated[
        str | None,
        typer.Option(
            "--period",
            "-p",
            help="A range in words: today, yesterday, '3 days ago', 'this week', 'last month'. "
            "--from/--to override their end of it.",
        ),
    ] = None,
    database: Annotated[str | None, typer.Option("--database", "-d", help="Only entries for this database.")] = None,
    verbose: Annotated[
        str | None,
        typer.Option(
            "--verbose",
            "--extract",
            metavar="FILE",
            help="Also write the raw log lines behind the output to FILE, readable without the server's logs.",
        ),
    ] = None,
    log_level: Annotated[str, typer.Option("--log-level")] = "WARNING",
):
    global _output_file, _output_format, _since, _until, _database, _verbose, _bounded
    if output_format not in output.FORMATS:
        typer.echo(f"Error: --output-format must be one of {', '.join(output.FORMATS)}", err=True)
        raise typer.Exit(1)

    _output_file = None if output_file == "-" else output_file
    _output_format = output_format
    _database = database
    _verbose = verbose

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _bounded = bool(period or from_ or to)

    try:
        _since, _until = parse.parse_bound(from_), parse.parse_bound(to)
        if period:
            start, end = parse.parse_period(period)
            _since, _until = _since or start, _until or end

        typer.echo(f"Getting logs from {_since} to {_until}", err=True)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


def _writer() -> output.Writer:
    return output.Writer(_output_file, _output_format)


def _scan(name: str, files: list[Path], keep: Callable[[dict[str, Any]], bool] | None = None) -> list[dict[str, Any]]:
    """Every command's rows come through here, so --verbose can't miss one.

    `keep` runs before the dump, so --verbose extracts what the command kept
    rather than everything the patterns matched.
    """
    rows = parse.scan(name, files, _since, _until, _database, source=bool(_verbose))
    if keep:
        rows = [row for row in rows if keep(row)]

    _dump(rows, "source")
    _nudge_unbounded(rows)

    return rows


def _nudge_unbounded(rows: list[dict[str, Any]]) -> None:
    """Say which span an unwindowed read covered, once it covers enough to
    matter. Advice, not a filter — narrowing is the reader's call, and a
    default that narrowed for them could hide a line they asked for."""
    if _bounded or len(rows) < NUDGE_ROWS:
        return

    typer.echo(
        f"Read {len(rows)} entries spanning {rows[0]['time']:%Y-%m-%d} to "
        f"{rows[-1]['time']:%Y-%m-%d}; -p today or -p 'this week' narrows it.",
        err=True,
    )


def _dump(rows: list[dict[str, Any]], key: str) -> None:
    """emoi's `--verbose`: the log lines behind the output, extracted so they
    can be read without access to the server."""
    if not _verbose:
        return

    with open(_verbose, "w") as fh:
        fh.writelines(row[key] for row in rows)

    typer.echo(f"{len(rows)} entries extracted to {_verbose}", err=True)


def _emit(name: str, files: list[Path], limit: int) -> None:
    """Every event command is this: scan, cut, print the command's columns."""
    rows = _scan(name, files)
    if limit:
        rows = rows[:limit]

    with _writer() as w:
        w.rows(patterns.COLUMNS[name], rows, no_wrap=TIMES)


@app.command()
def crons(
    files: LOGS,
    limit: LIMIT = 0,
    sort: Annotated[
        str, typer.Option("--sort", "-s", help=f"One of: {', '.join(patterns.CRON_STATS[1:])}.")
    ] = "t_total",
    events: Annotated[
        bool, typer.Option("--events", help="One row per event, not per cron: starts, failures, timeouts.")
    ] = False,
):
    """Cron timings, aggregated per cron job (ir_cron).

    Only runs that logged a duration can be aggregated: 17.0 and 18.0 log one
    at INFO, older versions only under `log_handler = <ir_cron logger>:DEBUG`.
    `--events` shows every event instead, including the ones that carry no
    timing — starts, failures and timeouts.
    """
    if events:
        _emit("crons", files, limit)
        return

    _check_sort(sort, patterns.CRON_STATS)
    rows = _scan("crons", files)
    ranked = cron_stats(rows, sort)

    if rows and not ranked:
        typer.echo(
            "No cron durations in these logs (16.0 and older log them at DEBUG only); --events shows what is there.",
            err=True,
        )

    with _writer() as w:
        _emit_stats(w, patterns.CRON_STATS, ranked, limit, f"{len(rows)} events, {len(ranked)} crons timed")


def cron_stats(rows: list[dict[str, Any]], sort: str = "t_total") -> list[dict[str, Any]]:
    """Collapse per-event rows into one row per cron.

    17.0 and 18.0 log one run's duration twice when the ir_cron logger is at
    DEBUG — `done in 0.018s` at INFO, then `... executed in 0.018s` at DEBUG —
    which would double every total. Dropping DEBUG wholesale would instead
    lose 16.0 and older, where INFO carries no duration at all.

    A pid's `log_handler` is fixed for its lifetime, so the pair is always
    emitted by one worker: pick per (db, pid). A concurrent worker, or another
    database on an older version, then decides on its own and keeps its
    DEBUG-only timings.
    """
    streams: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for row in rows:
        if row["duration"]:
            streams.setdefault((row["db"], row["pid"], row["cron"]), []).append(row)

    timings: dict[Any, list[float]] = {}
    for (_db, _pid, cron), runs in streams.items():
        counted = [run for run in runs if run["level"] == "INFO"] or runs
        timings.setdefault(cron, []).extend(float(run["duration"]) for run in counted)

    stats = [
        {
            "cron": cron,
            "count": len(times),
            "t_total": round(sum(times), 3),
            "t_avg": round(mean(times), 3),
            "t_min": min(times),
            "t_max": max(times),
        }
        for cron, times in timings.items()
    ]

    return _rank(stats, sort)


@app.command()
def logins(files: LOGS, limit: LIMIT = 0):
    """Successful logins: who, which database, from where."""
    _emit("logins", files, limit)


@app.command()
def users(
    files: LOGS,
    limit: LIMIT = 0,
    sort: Annotated[str, typer.Option("--sort", "-s", help=_sortable(patterns.USER_STATS))] = "count",
    aggregate: AGGREGATE = None,
):
    """Login activity per user: how often, over how many days.

    emoi's `users`, off the same lines as `logins` — so every version's
    wording counts, not just 10.0's. `avg`, `min` and `max` are logins per
    day and `days` is how many days the user appeared at all, so a user with
    one login a day for a week reads differently from one with seven in an
    afternoon.
    """
    _check_aggregate(aggregate)
    cols = _periodic(patterns.USER_STATS) if aggregate else patterns.USER_STATS
    _check_sort(sort, cols)

    rows = _scan("logins", files)
    ranked = user_stats(rows, sort, aggregate)

    with _writer() as w:
        _emit_stats(w, cols, ranked, limit, f"{len(rows)} logins, {len(ranked)} rows")


def user_stats(rows: list[dict[str, Any]], sort: str = "count", aggregate: str | None = None) -> list[dict[str, Any]]:
    """Collapse login rows into one row per user, or per user and period."""
    stats = []
    keyed = _group(rows, lambda row: (row["user"], bucket(row["time"], aggregate)))

    for (user, period), logins in keyed.items():
        times = [login["time"] for login in logins]
        daily = list(Counter(when.date() for when in times).values())

        stats.append({
            "user": user,
            "period": period,
            "count": len(logins),
            "avg": round(mean(daily), 2),
            "min": min(daily),
            "max": max(daily),
            "days": len(daily),
            "first": min(times),
            "last": max(times),
        })

    return _rank(stats, sort)


@app.command()
def usage(
    files: LOGS,
    limit: LIMIT = 0,
    sort: Annotated[str, typer.Option("--sort", "-s", help=_sortable(patterns.USAGE_STATS))] = "count",
    aggregate: AGGREGATE = None,
):
    """What the instance's traffic was for: logins, rpc, polling, static.

    emoi's `usage`. Its counters read `common.authenticate` and
    `/web/session/get_session_info`, which only an RPC client still hits;
    these classify werkzeug's access line instead, so a current web client
    is visible too. `--aggregate` is what makes it a trend rather than a
    total.
    """
    _check_aggregate(aggregate)
    cols = _periodic(patterns.USAGE_STATS) if aggregate else patterns.USAGE_STATS
    _check_sort(sort, cols)

    rows = _scan("calls", files)
    counts = Counter((parse.classify_route(row["route"]), bucket(row["time"], aggregate)) for row in rows)
    ranked: list[dict[str, Any]] = [
        {"type": kind, "period": period, "count": count} for (kind, period), count in counts.items()
    ]
    ranked = _rank(ranked, sort)

    with _writer() as w:
        _emit_stats(w, cols, ranked, limit, f"{len(rows)} requests, {len(ranked)} rows")


@app.command()
def passwords(files: LOGS, limit: LIMIT = 0):
    """Password changes: whose password, changed by whom, from where.

    Logged at INFO by res_users from 14.0 on; 16.0 added the `by` half.
    Before 14.0 this falls back to odoo.api, which needs a DEBUG handler.
    """
    _emit("passwords", files, limit)


@app.command()
def jobs(
    files: LOGS,
    limit: LIMIT = 0,
    stats: Annotated[bool, typer.Option("--stats", help="How long job runs took, instead of what happened.")] = False,
    sort: Annotated[str, typer.Option("--sort", "-s", help=_sortable(patterns.CALL_STATS))] = "t_total",
    aggregate: AGGREGATE = None,
):
    """queue_job runner lifecycle and per-job events.

    `--stats` reports timings instead. queue_job runs every job through
    `/queue_job/runjob`, so werkzeug's access line carries a job's duration
    and query count exactly the way it carries a request's — at INFO, 12.0
    on, no DEBUG handler, which is what `calls` reads.

    emoi keys its job stats on the method; nothing in that route or in any
    log line sampled names one, and the uuid it does carry is unique per run,
    so there is nothing to aggregate on it. `--aggregate` buckets by time
    instead — jobs per hour and what each cost, which is the throughput
    question emoi's own `--aggregate` answered.
    """
    if not stats:
        _emit("jobs", files, limit)
        return

    _check_aggregate(aggregate)
    cols = _periodic(patterns.CALL_STATS) if aggregate else patterns.CALL_STATS
    _check_sort(sort, cols)

    rows = _scan("calls", files, keep=lambda row: row["endpoint"] == patterns.JOB_ROUTE)
    # Before 12.0 the access line stops at the status, so it times nothing.
    timed = [row for row in rows if row["total"]]
    ranked = call_stats(timed, sort, aggregate)

    with _writer() as w:
        _emit_stats(w, cols, ranked, limit, f"{len(timed)} job runs, {len(ranked)} rows")


@app.command()
def workers(
    files: LOGS,
    limit: LIMIT = 0,
    stats: Annotated[bool, typer.Option("--stats", help="One row per worker instead of one per event.")] = False,
    sort: Annotated[str, typer.Option("--sort", "-s", help=_sortable(patterns.WORKER_STATS))] = "count",
    aggregate: AGGREGATE = None,
):
    """Worker births, deaths, timeouts and resource limits.

    `--stats` is emoi's `workers_stat`: one row per pid, with its `dob`/`dod`
    as `first`/`last`. The `t_` columns come from `WorkerCron (N) <db>
    time:2.386s`, the only worker line carrying a duration — `server.py`
    drops it after 15.0, so they are empty on 16.0 and later.
    """
    if not stats:
        _emit("workers", files, limit)
        return

    _check_aggregate(aggregate)
    cols = _periodic(patterns.WORKER_STATS) if aggregate else patterns.WORKER_STATS
    _check_sort(sort, cols)

    rows = _scan("workers", files)
    ranked = worker_stats(rows, sort, aggregate)

    with _writer() as w:
        _emit_stats(w, cols, ranked, limit, f"{len(rows)} events, {len(ranked)} workers")


def worker_stats(rows: list[dict[str, Any]], sort: str = "count", aggregate: str | None = None) -> list[dict[str, Any]]:
    """Collapse worker events into one row per pid."""
    stats = []
    keyed = _group(rows, lambda row: (row["worker"], bucket(row["time"], aggregate)))

    for (worker, period), events in keyed.items():
        times = [event["time"] for event in events]
        # Only WorkerCron logs a duration, and only while `mem:` was logged.
        runs = [float(event["duration"]) for event in events if event["duration"]]

        stats.append({
            "worker": worker,
            "period": period,
            # `Worker (853090) exiting.` names no type; a sibling event may.
            "kind": next((event["kind"] for event in events if event["kind"]), None),
            "count": len(events),
            "first": min(times),
            "last": max(times),
            "t_total": round(sum(runs), 3) if runs else None,
            "t_avg": round(mean(runs), 3) if runs else None,
            "t_min": min(runs) if runs else None,
            "t_max": max(runs) if runs else None,
        })

    return _rank(stats, sort)


@app.command()
def calls(
    files: LOGS,
    limit: LIMIT = 0,
    sort: Annotated[str, typer.Option("--sort", "-s", help=_sortable(patterns.CALL_SPLIT))] = "t_total",
    endpoint: Annotated[
        str | None, typer.Option("--endpoint", "-e", help="Only endpoints matching this regex.")
    ] = None,
    gt: Annotated[float, typer.Option("--gt", help="Only requests slower than this many seconds.")] = 0,
    min_count: Annotated[
        int, typer.Option("--min-count", help="Drop endpoints called fewer than this many times.")
    ] = 0,
    split: Annotated[bool, typer.Option("--split", help="Add t_sql and t_py, the two halves of t_avg.")] = False,
    aggregate: AGGREGATE = None,
    check_activity: Annotated[
        bool,
        typer.Option("--check-activity", help="Requests per period instead of per endpoint; implies --aggregate day."),
    ] = False,
):
    """Request timings from werkzeug's access line, grouped by endpoint.

    Needs Odoo 12.0+, which appends `query_count query_time remaining_time`
    to that line. It is logged at INFO, so no special handler is required.

    `--gt` with `--verbose` is emoi's slow-call export: the raw log lines of
    every request over the threshold, extracted to a file.

    Times are wall time. `--split` breaks t_avg into t_sql + t_py, which is
    the difference between an endpoint the database is slowing down and one
    the code is.

    `--aggregate` splits each endpoint per hour/day/week/month;
    `--check-activity` drops the endpoint and just counts traffic over time.
    """
    _check_aggregate(aggregate)
    # Sorting on a half implies wanting to see it.
    cols = patterns.CALL_SPLIT if split or sort in ("t_sql", "t_py") else patterns.CALL_STATS
    if aggregate:
        cols = _periodic(cols)
    if not check_activity:
        _check_sort(sort, cols)

    wanted = re.compile(endpoint) if endpoint else None
    rows = _scan("calls", files, keep=lambda row: _call_kept(row, wanted, gt))

    if check_activity:
        ranked = activity_stats(rows, aggregate or "day")

        with _writer() as w:
            _emit_stats(w, patterns.ACTIVITY_STATS, ranked, limit, f"{len(rows)} requests, {len(ranked)} periods")

        return

    # Requests from before 12.0 carry no timing; they cannot be aggregated.
    timed = [row for row in rows if row["total"]]
    ranked = [stat for stat in call_stats(timed, sort, aggregate) if stat["count"] >= min_count]

    with _writer() as w:
        _emit_stats(w, cols, ranked, limit, f"{len(timed)} requests, {len(ranked)} distinct")


def activity_stats(rows: list[dict[str, Any]], aggregate: str = "day") -> list[dict[str, Any]]:
    """emoi's `--check-activity`: how busy the instance was, period by period.

    Untimed requests count here — the question is traffic, not duration, so
    a pre-12.0 log answers it as well as any other.
    """
    counts = Counter(bucket(row["time"], aggregate) for row in rows)

    return [{"period": period, "count": count} for period, count in sorted(counts.items(), reverse=True)]


def _call_kept(row: dict[str, Any], wanted: re.Pattern[str] | None, gt: float) -> bool:
    if wanted and not wanted.search(row["endpoint"]):
        return False

    # A request with no timing at all can't be shown to be over a bound.
    return not gt or bool(row["total"] and row["total"] > gt)


def _check_sort(sort: str, cols: list[str]) -> None:
    """The key column can't be sorted on; every other column can."""
    if sort not in cols[1:]:
        typer.echo(f"Error: --sort must be one of {', '.join(cols[1:])}", err=True)
        raise typer.Exit(1)


def _check_aggregate(aggregate: str | None) -> None:
    if aggregate and aggregate not in AGGREGATES:
        typer.echo(f"Error: --aggregate must be one of {', '.join(AGGREGATES)}", err=True)
        raise typer.Exit(1)


def bucket(when: datetime, aggregate: str | None) -> str | None:
    """The period a row falls in, labelled so that sorting it sorts by time.

    Weeks are ISO and carry their year — emoi's bare `week 33` collapses the
    same week of every year into one row.
    """
    if aggregate == "hour":
        return when.strftime("%Y-%m-%d %H:00")
    if aggregate == "day":
        return when.strftime("%Y-%m-%d")
    if aggregate == "week":
        year, week, _ = when.isocalendar()
        return f"{year}-W{week:02d}"
    if aggregate == "month":
        return when.strftime("%Y-%m")

    return None


def _periodic(cols: list[str]) -> list[str]:
    """`period` sits next to the key it splits, and is sortable like any column."""
    return [cols[0], "period", *cols[1:]]


def _sortable(cols: list[str]) -> str:
    """--sort's help. `period` only exists under --aggregate, but listing it
    only there would need two help strings; `_check_sort` refuses it when the
    column isn't in play, and says so."""
    return f"One of: {', '.join(_periodic(cols)[1:])} (period needs --aggregate)."


def _rank(stats: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Sort a stats table, biggest first.

    A column can be empty on some rows and not others — a worker that logged
    no duration, a version that logs none at all — so None sorts last instead
    of raising. Rows that both have one never reach the second key.
    """
    stats.sort(key=lambda s: (s[sort] is not None, s[sort] if s[sort] is not None else 0), reverse=True)

    return stats


def _group(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)

    return grouped


def call_stats(rows: list[dict[str, Any]], sort: str = "t_total", aggregate: str | None = None) -> list[dict[str, Any]]:
    """Collapse per-request rows into one row per endpoint, or per endpoint
    and period once `--aggregate` splits them."""
    stats = []
    keyed = _group(rows, lambda row: (row["endpoint"], bucket(row["time"], aggregate)))

    for (endpoint, period), requests in keyed.items():
        times = [request["total"] for request in requests]

        stats.append({
            "endpoint": endpoint,
            "period": period,
            "count": len(times),
            "t_total": round(sum(times), 3),
            "t_avg": round(mean(times), 3),
            "t_min": min(times),
            "t_max": max(times),
            # The mean of a route is dragged around by one slow request.
            "t_median": round(median(times), 3),
            # The two halves of t_avg. `remaining_time` is everything that
            # isn't SQL — usually Python, but also lock waits and outbound
            # calls, so t_py is "not the database" rather than "CPU".
            "t_sql": round(mean(request["query_time"] for request in requests), 3),
            "t_py": round(mean(request["other_time"] for request in requests), 3),
            "q_avg": round(mean(request["queries"] for request in requests), 1),
        })
    return _rank(stats, sort)


def _emit_stats(w: output.Writer, cols: list[str], stats: list[dict[str, Any]], limit: int, footer: str) -> None:
    if limit:
        stats = stats[:limit]

    w.rows(cols, stats, no_wrap=TIMES)
    w.footer(footer)


@app.command()
def errors(
    files: LOGS,
    limit: LIMIT = 0,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            "-x",
            help="Drop entries matching this regex; repeatable. Common noise: -x 'raise_exception=False' -x Loading",
        ),
    ] = None,
    logger: Annotated[
        str | None,
        typer.Option(
            "--logger",
            "-l",
            help="Only entries whose logger matches this regex: -l ir_cron, -l 'queue_job|werkzeug'.",
        ),
    ] = None,
    traceback_only: Annotated[
        bool, typer.Option("--traceback-only", help="Only entries carrying a traceback.")
    ] = False,
):
    """ERROR and CRITICAL entries, grouped by exception type and message.

    `--logger` is the general form of emoi's `-c cron/job/http`: those are
    just the ir_cron, queue_job and werkzeug loggers.
    """
    dropped = [re.compile(x) for x in exclude or []]
    wanted = re.compile(logger) if logger else None
    entries = []

    for block in parse.blocks(files, _since, _until, _database):
        if wanted and not wanted.search(block["logger"]):
            continue
        if traceback_only and "Traceback" not in block["text"]:
            continue
        if any(x.search(block["text"]) for x in dropped):
            continue

        entries.append(block)

    entries.sort(key=lambda entry: entry["time"])
    # An error is its whole entry, traceback included — not just the head line.
    _dump(entries, "text")
    _nudge_unbounded(entries)

    with _writer() as w:
        _emit_grouped(w, entries, limit)


def _emit_grouped(w: output.Writer, entries: list[dict[str, Any]], limit: int) -> None:
    counts: Counter[tuple[str, str]] = Counter()
    seen: dict[tuple[str, str], list[datetime]] = {}

    for entry in entries:
        key = (entry["type"], _squash(entry["error"]))
        counts[key] += 1
        seen.setdefault(key, []).append(entry["time"])

    ranked = counts.most_common(limit or None)
    rows = [
        {
            "type": key[0],
            "error": key[1],
            "count": count,
            "first": min(seen[key]),
            "last": max(seen[key]),
        }
        for key, count in ranked
    ]

    w.rows(["type", "error", "count", "first", "last"], rows, no_wrap=TIMES)
    w.footer(f"{len(entries)} entries, {len(counts)} distinct")


def _squash(error: str) -> str:
    """Normalise an error into a group key.

    Odoo puts the pid or record id in parentheses (`WorkerHTTP (3222624)
    timeout`), which would otherwise split one recurring failure into one
    group per process. Only parenthesised numbers are collapsed — a bare
    number is usually part of the message (`timeout after 3600s`).
    """
    squashed = re.sub(r"\s+", " ", error or "").strip()

    return re.sub(r"\((\d+)\)", "(N)", squashed)
