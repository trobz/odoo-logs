"""Every command against the corpus, plus the grain-level parsers."""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest

from odoo_logs import main, output, parse, patterns


def rows(name: str, logs: list[Path], **kw) -> list[dict]:
    return parse.scan(name, logs, **kw)


def field(rows: list[dict], key: str) -> list:
    return [row[key] for row in rows]


# --- commands -------------------------------------------------------------


def test_crons_reads_every_version_wording(logs):
    found = rows("crons", logs)
    events = {(row["cron"], row["event"]) for row in found}

    # 11.0 backtick pair, 11.0 failure, 16.0 duration line, 18.0 quoted+id
    assert ("Base: Auto-vacuum internal data", "Starting job") in events
    assert ("Base: Auto-vacuum internal data", "done") in events
    assert ("Sales: Send pending emails", "failed") in events
    assert ("long cron", "completed") in events
    # 15.0-17.0 direct trigger; its `done` half matches a different pattern
    assert ("Vacuum temporary reports", "Manually starting job") in events
    # 10.0 failures name the call, not the cron, so a row may carry no name.
    assert any((row["cron"] or "").startswith("Notification:") for row in found)


def test_crons_extracts_duration_from_both_shapes(logs):
    by_event = {row["event"]: row["duration"] for row in rows("crons", logs)}

    assert by_event["done in 40.564s"] == "40.564"  # 18.0, inside the message
    assert by_event["server action 1328 with uid 1"] == "0.006"  # 16.0, prefix


def test_crons_catch_failures_on_every_version(logs):
    """Each version words a failed cron differently, and 18.0 moved it into
    the `Job %r (%s) ...` line it uses for everything else."""
    by_cron = {row["cron"]: row["event"] for row in rows("crons", logs)}

    assert by_cron["Sales: Send pending emails"] == "failed"  # 11.0
    assert by_cron["Notification: Send scheduled message notifications"] == "failed"  # 16.0
    assert by_cron["long cron"] == "timed out"  # 18.0, last event wins
    # 10.0 names no cron, only the call it made
    assert "Call of self.env['ir.autovacuum'].power_on(*[]) failed" in by_cron[None]


def test_crons_read_the_debug_timing_line(logs):
    """It is the only carrier of a duration before 17.0, and 18.0 renders the
    cron name with `%r`, which switches to `"` when the name has an apostrophe.
    """
    by_cron = {row["cron"]: row for row in rows("crons", logs)}

    assert by_cron["Bob's cron"]["duration"] == "0.500"  # 18.0
    assert by_cron["Vacuum temporary reports"]["duration"] == "0.123"  # 17.0
    assert by_cron["Vacuum temporary reports"]["event"] == "done"


def test_crons_keeps_cron_id_when_the_version_logs_one(logs):
    by_job = {row["cron"]: row["cron_id"] for row in rows("crons", logs)}

    assert by_job["long cron"] == "76"
    assert by_job["Sales: Send pending emails"] == "35"
    assert by_job["Base: Auto-vacuum internal data"] is None


def test_logins_reads_every_logger_name(logs):
    """9.0/10.0 log it from `service.common`, 11.0 from `base.res.res_users`,
    13.0 on from `base.models.res_users`."""
    found = rows("logins", logs)

    assert field(found, "user") == ["pnguyen", "jdoe", "admin", "admin"]
    assert field(found, "db") == ["odoo9", "odoo11", "odoo16", "odoo18"]
    # The oldest wording names the database but no address at all.
    assert field(found, "ip") == [None, "127.0.0.1", "n/a", "127.0.0.1"]


def test_jobs_pulls_the_uuid_out_of_the_message(logs):
    """Only the controller's wording puts the uuid where a group can capture
    it; the jobrunner's carry it mid-sentence, where UUID_RE finds it."""
    found = rows("jobs", logs)
    asked = next(row for row in found if row["event"].startswith("asking Odoo"))

    assert asked["job"] == "c5326dc9-96c0-4568-961e-2dfe3ecd323a"
    assert asked["db"] == "odoo18"  # `on db X` beats the head's `?`
    assert "Configured channel: root(C:1,Q:0,R:0,F:0)" in field(found, "event")


def test_jobs_read_the_controller_that_actually_runs_them(logs):
    """Per-job events come from queue_job.controllers.main, at DEBUG. emoi
    keys on the `queue_job.job` logger, which logs nothing per run — no
    corpus sampled has a line from it."""
    found = {row["event"]: row for row in rows("jobs", logs)}
    done = found["done"]

    assert (done["job"], done["priority"]) == ("553d4994-0e77-414d-9998-acd2f80dd2d6", "10")
    assert "enqueue depends started" in found
    # The jobrunner's own view of the same job, from a different logger.
    assert any("marked done in channel" in event for event in found)


def test_jobs_stats_come_off_the_runjob_access_line(logs):
    """queue_job runs every job through /queue_job/runjob, so werkzeug times
    a job exactly the way it times a request — INFO, no DEBUG handler."""
    run = next(row for row in rows("calls", logs) if row["endpoint"] == patterns.JOB_ROUTE)

    assert run["total"] == 0.111  # 0.084 + 0.027
    assert run["queries"] == 22


def test_workers_distinguishes_named_from_anonymous(logs):
    by_worker = {row["worker"]: row for row in rows("workers", logs)}

    assert by_worker["384363"]["kind"] == "WorkerHTTP"
    assert by_worker["384363"]["event"] == "alive"
    assert by_worker["384364"]["event"] == "timeout after 3600s"
    assert by_worker["853077"]["event"] == "polling for jobs"
    # `Worker (853090) exiting.` carries no worker type
    assert by_worker["853090"]["kind"] is None


def test_workers_keep_the_cron_run_time_they_parse(logs):
    """`WorkerCron (N) <db> time:2.386s mem: …` is the one worker line with a
    duration on it, and the one naming the database it ran for. Both were
    being parsed and then dropped on the floor."""
    found = rows("workers", logs)
    run = next(row for row in found if row["duration"] == "2.386")

    assert (run["worker"], run["db"], run["kind"]) == ("9374", "odoo9", "WorkerCron")
    # Events with no timing must not pick one up from the `mem:` half.
    assert all(row["duration"] is None for row in found if "time:" not in row["event"])


def test_worker_stats_rank_the_timed_above_the_untimed(logs):
    """emoi's `workers_stat`, minus the memory it read beside these: `dob`
    and `dod` are `first`/`last`. Only WorkerCron on 15.0 and older logs a
    duration, so most rows have none — and those must sort last, not raise.
    """
    stats = main.worker_stats(rows("workers", logs), sort="t_total")
    busiest = stats[0]

    assert (busiest["worker"], busiest["count"]) == ("9374", 2)
    assert busiest["t_total"] == 316.977  # 314.591 + 2.386
    assert (busiest["t_min"], busiest["t_max"]) == (2.386, 314.591)
    assert busiest["first"] == datetime(2018, 4, 10, 14, 5, 37, 568000)
    assert busiest["last"] == datetime(2018, 4, 10, 15, 7, 0, 685000)
    assert all(stat["t_total"] is None for stat in stats[1:])
    # `Worker (853090) exiting.` names no type and has no sibling event to lend one.
    assert next(stat for stat in stats if stat["worker"] == "853090")["kind"] is None


def test_errors_groups_by_the_raised_exception(logs):
    found = list(parse.blocks(logs))
    by_type = {}
    for block in found:
        by_type.setdefault(block["type"], []).append(block)

    # Both http entries raise the same KeyError and must land in one group.
    assert len(by_type["KeyError"]) == 2
    assert by_type["KeyError"][0]["error"] == "'socket'"
    # A single-line error has no traceback: it falls back to logger + message.
    assert by_type["odoo.modules.registry"][0]["error"].startswith("Model x_bi")


def test_errors_attach_their_traceback_and_stop_at_the_next_entry(logs):
    block = next(b for b in parse.blocks(logs) if b["type"] == "KeyError")

    assert block["text"].count("Traceback (most recent call last)") == 1
    assert "websocket.py" in block["text"]
    assert "Login successful" not in block["text"]


def test_errors_ignores_non_error_levels(logs):
    assert {block["level"] for block in parse.blocks(logs)} == {"ERROR"}


def test_passwords_read_the_info_line_on_both_wordings(logs):
    named = [row for row in rows("passwords", logs) if row["user"]]

    # 16.0+ names the actor; 14.0/15.0 only names the subject.
    assert field(named, "user") == ["jdoe", "admin"]
    assert field(named, "uid") == ["7", "2"]
    assert field(named, "by") == [None, "admin"]
    assert field(named, "ip") == ["10.20.14.220", "127.0.0.1"]


def test_passwords_fall_back_to_odoo_api_before_14(logs):
    """Pre-14.0 logs nothing at INFO, so emoi's `odoo.api` DEBUG line is all
    there is. It names the wizard, never who changed whose password — which
    is why it is the fallback and not the source."""
    wizard = next(row for row in rows("passwords", logs) if not row["user"])

    assert (wizard["model"], wizard["event"]) == ("change.password.wizard", "change_password_button")
    assert wizard["by"] is None


def test_calls_key_call_kw_routes_on_model_and_method(logs):
    by_endpoint = {row["endpoint"]: row for row in rows("calls", logs)}

    call_kw = by_endpoint["product.product.web_read"]
    assert (call_kw["model"], call_kw["method"]) == ("product.product", "web_read")
    # total is query_time + remaining_time
    logo = by_endpoint["/web/binary/company_logo"]
    assert (logo["queries"], logo["total"]) == (4, 0.031)


def test_calls_key_other_routes_on_the_path_with_ids_collapsed(logs):
    """A static or image route's tail is a filename, not a model and method."""
    by_endpoint = {row["endpoint"]: row for row in rows("calls", logs)}

    # `/web/image/res.partner/3/avatar_128?unique=…` — id out, query string out
    avatar = by_endpoint["/web/image/res.partner/N/avatar_128"]
    assert (avatar["model"], avatar["method"]) == (None, None)


def test_calls_tolerate_versions_that_log_no_timing(logs):
    """Odoo only appends perf_info from 12.0; 11.0 stops after the status."""
    poll = next(r for r in rows("calls", logs) if r["endpoint"] == "/longpolling/poll")

    assert poll["status"] == "200"
    assert poll["total"] is None
    assert poll["queries"] is None


def test_cron_stats_aggregate_only_runs_that_logged_a_duration(logs):
    """emoi's view. A cron whose every event is start/done/failed with no
    timing has nothing to average and must not show up as a zero."""
    stats = {s["cron"]: s for s in main.cron_stats(rows("crons", logs))}

    # pid 380367 logged one run `done in 40.564s` at INFO and again at DEBUG —
    # counting both makes it two runs. pid 380999 ran the same cron for 10s
    # and must still count, so the pair cannot be resolved per cron name.
    assert stats["long cron"]["count"] == 2
    assert stats["long cron"]["t_total"] == 50.564
    # 16.0 and older have only the DEBUG timing, which must still count.
    assert stats["Bob's cron"]["count"] == 1
    assert "Base: Auto-vacuum internal data" not in stats  # 11.0 INFO, no timing


def test_call_stats_aggregate_per_endpoint(logs):
    found = [row for row in rows("calls", logs) if row["total"]]
    stats = main.call_stats(found)

    web_read = next(s for s in stats if s["endpoint"] == "product.product.web_read")
    assert web_read["count"] == 2
    assert web_read["t_total"] == 0.427  # 0.329 + 0.098
    assert (web_read["t_min"], web_read["t_max"]) == (0.098, 0.329)
    assert web_read["t_median"] == 0.214  # emoi reports one; the mean alone lies
    # --split's two halves must reconstruct t_avg, or they mean nothing.
    assert round(web_read["t_sql"] + web_read["t_py"], 3) == web_read["t_avg"]


def test_call_stats_split_one_endpoint_across_periods(logs):
    """emoi's --aggregate: the same endpoint on two days is two rows."""
    found = [row for row in rows("calls", logs) if row["total"]]
    whole = {stat["endpoint"]: stat["count"] for stat in main.call_stats(found)}
    daily = {(stat["endpoint"], stat["period"]): stat["count"] for stat in main.call_stats(found, aggregate="day")}

    assert whole["/web/login"] == 2
    assert daily[("/web/login", "2026-08-14")] == 1
    assert daily[("/web/login", "2026-08-17")] == 1
    # Two requests inside one bucket stay one row.
    assert daily[("product.product.web_read", "2026-08-13")] == 2


def test_activity_stats_count_requests_the_timing_view_drops(logs):
    """--check-activity asks about traffic, not duration, so 11.0's untimed
    access line counts — `call_stats` has to leave it out, this must not."""
    found = rows("calls", logs)
    activity = main.activity_stats(found)

    assert sum(period["count"] for period in activity) == len(found)
    assert {"period": "2025-04-02", "count": 1} in activity  # /longpolling/poll
    assert activity == sorted(activity, key=lambda period: period["period"], reverse=True)


def test_user_stats_average_over_the_days_a_user_appeared():
    """emoi's avg/min/max are logins per day, not per row: two logins in one
    afternoon and one the next morning is max 2, min 1, over 2 days."""
    logins = [
        {"user": "admin", "time": datetime(2026, 8, 4, 8, 1)},
        {"user": "admin", "time": datetime(2026, 8, 4, 17, 40)},
        {"user": "admin", "time": datetime(2026, 8, 5, 9, 0)},
    ]
    (stat,) = main.user_stats(logins)

    assert (stat["count"], stat["days"], stat["min"], stat["max"]) == (3, 2, 1, 2)
    assert stat["avg"] == 1.5
    assert (stat["first"], stat["last"]) == (logins[0]["time"], logins[2]["time"])


def test_user_stats_read_every_version_of_the_login_line(logs):
    """emoi's `users` keys on 10.0's wording alone; ours is the `logins`
    scan, so a login logged by any version counts."""
    stats = {stat["user"]: stat for stat in main.user_stats(rows("logins", logs))}

    assert (stats["admin"]["count"], stats["admin"]["days"]) == (2, 2)  # 16.0, 18.0
    assert stats["jdoe"]["count"] == 1  # 11.0


@pytest.mark.parametrize(
    "route,kind",
    [
        ("/web/dataset/call_kw/product.product/web_read", "rpc"),
        ("/web/login", "login"),
        ("/web/image/res.partner/3/avatar_128?unique=1773779145000", "static"),
        ("/longpolling/poll", "poll"),
        ("/queue_job/runjob?db=odoo16&job_uuid=553d4994-0e77-414d-9998-acd2f80dd2d6", "job"),
        ("/mail/thread/data", "other"),
    ],
)
def test_usage_classifies_the_route_not_the_endpoint(route, kind):
    """`endpoint` folds call_kw down to `model.method`, which no longer says
    what kind of request it was, so the class comes off the raw route."""
    assert parse.classify_route(route) == kind


# --- filters --------------------------------------------------------------


def test_time_bounds_are_inclusive(logs):
    at = datetime(2026, 8, 4, 8, 1, 34, 187000)
    found = rows("logins", logs, since=at, until=at)

    assert field(found, "db") == ["odoo18"]


def test_time_bounds_apply_to_errors_too(logs):
    """`blocks` took since/until/database and dropped them on the floor, so
    every filter was silently ignored on the one command that reads it."""
    early = datetime(2026, 6, 8, 2, 18, 2, 95000)
    kept = list(parse.blocks(logs, until=early))

    assert 0 < len(kept) < len(list(parse.blocks(logs)))
    assert all(block["time"] <= early for block in kept)
    assert {block["db"] for block in parse.blocks(logs, database="odoo16")} == {"odoo16"}


def test_database_filter_matches_the_resolved_db(logs):
    # The jobrunner logs `?` as the db; the filter must see `odoo18` anyway.
    found = rows("jobs", logs, database="odoo18")

    assert field(found, "job") == ["c5326dc9-96c0-4568-961e-2dfe3ecd323a"]


def test_rotated_files_come_back_in_time_order(logs):
    times = field(rows("crons", logs), "time")

    assert times == sorted(times)


# --- grain ----------------------------------------------------------------


def test_every_format_writes_the_same_rows(tmp_path: Path):
    """`rows` is the one path every command emits through, so a format that
    drops a column — or a footer leaking into csv as a bogus row — is silent.
    """
    data = [{"time": datetime(2026, 8, 13, 10, 18, 7), "cron": "test", "duration": None}]
    written = {}

    for fmt in output.FORMATS:
        path = tmp_path / fmt
        with output.Writer(str(path), fmt) as w:
            w.rows(["time", "cron", "duration"], data)
            w.footer("1 crons timed")

        written[fmt] = path.read_text()

    assert written["csv"].splitlines() == ["time,cron,duration", "2026-08-13 10:18:07,test,"]
    assert json.loads(written["json"]) == [{"time": "2026-08-13 10:18:07", "cron": "test", "duration": None}]
    assert "1 crons timed" in written["text"]


def test_every_pattern_has_a_line(logs):
    """A pattern with nothing behind it goes dead silently — a version renames
    a wording, the regex stops matching, and no test notices. A new pattern
    brings its captured line, or it does not go in.
    """
    lines = [line for path in logs for line in parse.open_log(path)]
    missing = [
        (name, i)
        for name, regexes in patterns.PATTERNS.items()
        for i, regex in enumerate(regexes)
        if not any(regex.match(line) for line in lines)
    ]

    assert missing == []


@pytest.mark.parametrize("name", sorted(patterns.PATTERNS))
def test_every_pattern_starts_with_head(name):
    """`scan` skips lines HEAD_RE rejects, so a pattern that can match one
    would go silently dead."""
    for source in patterns._SOURCES[name]:
        assert source.startswith(patterns.HEAD)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-13", datetime(2026, 8, 13)),
        ("2026-08-13 01:58", datetime(2026, 8, 13, 1, 58)),
        ("2026-08-13 01:58:36", datetime(2026, 8, 13, 1, 58, 36)),
        ("2026-08-13 01:58:36,578", datetime(2026, 8, 13, 1, 58, 36, 578000)),
    ],
)
def test_parse_bound_accepts_every_precision(raw, expected):
    assert parse.parse_bound(raw) == expected


def test_parse_bound_rejects_junk():
    with pytest.raises(ValueError, match="unrecognized date"):
        parse.parse_bound("last tuesday")


# A Tuesday, so `this week` starts two days back and `last week` is a whole one.
NOW = datetime(2026, 8, 18, 14, 30)


def midnight(year: int, month: int, day: int) -> datetime:
    """The last instant of a day — where a finished period ends."""
    return datetime(year, month, day, 23, 59, 59, 999999)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("today", (datetime(2026, 8, 18), midnight(2026, 8, 18))),
        ("yesterday", (datetime(2026, 8, 17), midnight(2026, 8, 17))),
        ("3 days ago", (datetime(2026, 8, 15, 14, 30), NOW)),
        ("2 hours ago", (datetime(2026, 8, 18, 12, 30), NOW)),
        # A period still running ends now; a finished one ends where it ended.
        ("this week", (datetime(2026, 8, 17), NOW)),
        ("last week", (datetime(2026, 8, 10), midnight(2026, 8, 16))),
        ("last month", (datetime(2026, 7, 1), midnight(2026, 7, 31))),
        ("last year", (datetime(2025, 1, 1), midnight(2025, 12, 31))),
    ],
)
def test_parse_period_reads_emois_grammar(raw, expected):
    assert parse.parse_period(raw, NOW) == expected


def test_unbounded_read_nudges_only_when_it_covered_a_lot(monkeypatch, capsys):
    """The hint exists so a whole-file read is visible, not so every run is
    noisy: a small log stays quiet, and an explicit window always does."""
    rows = [{"time": NOW}] * main.NUDGE_ROWS
    monkeypatch.setattr(main, "_bounded", False)

    main._nudge_unbounded(rows[:10])
    assert capsys.readouterr().err == ""

    main._nudge_unbounded(rows)
    assert "narrows it" in capsys.readouterr().err

    # A window was asked for, so its span is not news.
    monkeypatch.setattr(main, "_bounded", True)
    main._nudge_unbounded(rows)
    assert capsys.readouterr().err == ""


def test_parse_period_clamps_a_month_too_short_to_land_on():
    """31 March, a month back, is the end of February — not 3 March."""
    since, _ = parse.parse_period("1 month ago", datetime(2026, 3, 31, 9, 0))

    assert since == datetime(2026, 2, 28, 9, 0)


def test_parse_period_rejects_what_it_cannot_parse():
    """The grammar is emoi's and no wider; anything else is refused rather
    than guessed at."""
    with pytest.raises(ValueError, match="unrecognized period"):
        parse.parse_period("last tuesday")


def test_bucket_labels_sort_in_time_order():
    """emoi's `week 33` collapses that week of every year into one row."""
    assert main.bucket(NOW, "hour") == "2026-08-18 14:00"
    assert main.bucket(NOW, "week") == "2026-W34"
    assert main.bucket(NOW, "month") == "2026-08"
    assert main.bucket(NOW, None) is None


def test_undecodable_bytes_do_not_stop_the_scan(tmp_path: Path):
    """Odoo writes raw bytes into logs; a bad one must not kill the file."""
    path = tmp_path / "server.log"
    path.write_bytes(
        b"2026-08-12 02:01:42,272 384363 INFO odoo18 odoo.service.server: "
        b"Worker WorkerHTTP (384363) al\xffve\n"
        b"2026-08-13 01:58:36,578 1325751 ERROR odoo18 odoo.service.server: "
        b"WorkerCron (384364) timeout after 3600s\n"
    )

    assert field(rows("workers", [path]), "worker") == ["384363", "384364"]


def test_a_file_ending_mid_traceback_still_yields_its_entry(tmp_path: Path):
    path = tmp_path / "server.log.1.gz"
    with gzip.open(path, "wt") as fh:
        fh.write(
            "2026-07-23 07:25:29,069 1496426 ERROR odoo18 odoo.http: boom\n"
            "Traceback (most recent call last):\n"
            "KeyError: 'socket'\n"
        )

    (block,) = parse.blocks([path])

    assert block["type"] == "KeyError"


def test_lines_before_the_first_entry_are_not_swallowed(tmp_path: Path):
    """click-odoo-contrib prints tracebacks with no timestamped head."""
    path = tmp_path / "server.log"
    path.write_text(
        "Traceback (most recent call last):\n"
        "odoo.exceptions.UserError: orphaned, belongs to no entry\n"
        "2026-06-08 02:18:02,095 1715906 ERROR odoo18 odoo.modules.registry: no table.\n"
    )

    (block,) = parse.blocks([path])

    assert "orphaned" not in block["text"]


def test_recurring_failures_group_across_processes():
    """The pid in `WorkerHTTP (3222624) timeout` must not split the group."""
    same = {
        main._squash("WorkerHTTP (3222624) timeout after 3600s"),
        main._squash("WorkerHTTP (384363) timeout after 3600s"),
    }

    assert len(same) == 1
    # A bare number carries meaning and is kept.
    assert "3600s" in same.pop()
