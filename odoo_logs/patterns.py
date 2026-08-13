"""Regex table: one entry per command, all known Odoo wordings per entry.

Loggers and messages are renamed between Odoo versions (`base.ir.ir_cron` on
10.0/11.0, `base.models.ir_cron` on 16.0/18.0; `base.res.res_users` on 11.0,
`base.models.res_users` after), so each command matches an alternation rather
than assuming a version.

Every pattern here has a real log line behind it in `tests/sample.log`, drawn
from 9.0 through 18.0 instances; `test_every_pattern_has_a_line` enforces it,
so a wording that goes dead fails rather than quietly matching nothing.
"""

from __future__ import annotations

import re

TIME = r"(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
ODOO = r"(?:odoo|openerp)"

# db is `?` on lines logged outside a registry (jobrunner, server startup).
HEAD = rf"^{TIME} (?P<pid>\d+) (?P<level>[A-Z]+) (?P<db>\S+) "

HEAD_RE = re.compile(rf"{HEAD}(?P<logger>[\w.]+): (?P<message>.*)")

# Last frame of a traceback — the line errors are grouped by.
EXCEPTION_RE = re.compile(
    r"^(?P<type>[\w.]*(?:Error|Exception|Warning|Exit|Interrupt|Abort))"
    r"(?:: (?P<error>.*))?$"
)

UUID_RE = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b")

# Only call_kw/call_button put a model and a method in the path. Every other
# route's tail is just a filename (`/web/image/42/description/icon.png`), so
# reading it as model+method is nonsense.
CALL_KW_RE = re.compile(r"/call_(?:kw|button)/(?P<model>[^/]+)/(?P<method>[^/]+)/?$")
# Record ids in a route would otherwise make one group per record.
ROUTE_ID_RE = re.compile(r"/\d+(?=/|$)")
DURATION_RE = re.compile(r"(?:done in|executed in|time:)\s*(?P<duration>[\d.]+)s")
ALT_DB_RE = re.compile(r"(?:on db|using database|for db:) '?(?P<alt_db>[^' ]+)'?")

# Every queue_job run goes through this route, 10.0 through 19.0, so
# werkzeug's access line carries a job's duration the way it carries a
# request's. The uuid rides in the query string and is unique per run.
JOB_ROUTE = "/queue_job/runjob"

# Source strings; compiled into PATTERNS below.
_SOURCES: dict[str, list[str]] = {
    "crons": [
        # 18.0: Job 'long cron' (76) starting | done in 40.564s | completed
        # | timed out | server action #12 failed. `%r` on a name carrying an
        # apostrophe quotes it with `"` instead, so both quotes are accepted.
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models\.|ir\.)?ir_cron: "
        rf"Job ['\"](?P<cron>.*?)['\"] \((?P<cron_id>\d+)\) (?P<event>.*?)\s*$",
        # 17.0 only: Job done: `Vacuum temporary reports` (0.123s).
        rf"{HEAD}{ODOO}\.addons\.base\.models\.ir_cron: "
        rf"Job (?P<event>done): `(?P<cron>[^`]*)` \((?P<duration>[\d.]+)s\)",
        # 11.0: Starting job `Cron job to update the Groups`.
        # 15.0-17.0 word the direct trigger `Manually starting job `x`.`, whose
        # `Job `x` done.` half matches below — without this it is a half record.
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models\.|ir\.)?ir_cron: "
        rf"(?P<event>(?:Manually starting|Starting) job) `(?P<cron>[^`]*)`",
        # 11.0: Job `Cron job to update the Groups` done.
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models\.|ir\.)?ir_cron: "
        rf"Job `(?P<cron>[^`]*)` (?P<event>.*?)\.?\s*$",
        # 11.0: Call from cron <name> for server action #963 failed in Job #35
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models\.|ir\.)?ir_cron: "
        rf"Call from cron (?P<cron>.*?) for server action #?\d+ "
        rf"(?P<event>failed) in Job #?(?P<cron_id>\d+)",
        # 10.0: Call of self.pool.get('ir.autovacuum').power_on(...) failed in Job 1
        rf"{HEAD}{ODOO}\.addons\.base\.ir\.ir_cron: "
        rf"(?P<event>Call of .*failed) in Job #?(?P<cron_id>\d+)",
        # 16.0: 0.006s (cron Notification: Send ..., server action 1328 with uid 1)
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models\.|ir\.)?ir_cron: "
        rf"(?P<duration>[\d.]+)s \((?:cron )?(?P<cron>.*?), "
        rf"(?P<event>server action \d+ with uid \d+)\)",
        # 10.0: 5.352s (ir.autovacuum, power_on)
        rf"{HEAD}{ODOO}\.addons\.base\.ir\.ir_cron: "
        rf"(?P<duration>[\d.]+)s \((?P<cron>[^,]+), (?P<event>[^)]+)\)",
    ],
    "logins": [
        # 16.0/18.0 use base.models.res_users, 11.0 uses base.res.res_users
        rf"{HEAD}{ODOO}\.addons\.base\.(?:models|res)\.res_users: "
        rf"Login successful for db:(?P<alt_db>\S+) login:(?P<user>\S+) "
        rf"from (?P<ip>\S+)",
        # 10.0
        rf"{HEAD}{ODOO}\.service\.common: successful login from "
        rf"'(?P<user>[^']*)' using database '(?P<alt_db>[^']*)'",
    ],
    # res_users logs the change at INFO, so this works on a default handler.
    # The wizard ids in the odoo.api DEBUG line say nothing about who changed
    # whose password; these carry both. Odoo grew the `by` half in 16.0.
    "passwords": [
        # 16.0+: Password change for 'admin' (#2) by 'admin' (#2) from 127.0.0.1
        rf"{HEAD}{ODOO}\.addons\.base\.models\.res_users: "
        rf"Password change for '(?P<user>[^']*)' \(#(?P<uid>\d+)\) "
        rf"by '(?P<by>[^']*)' \(#(?P<by_uid>\d+)\) from (?P<ip>\S+)",
        # 14.0/15.0: Password change for 'admin' (#2) from 127.0.0.1
        rf"{HEAD}{ODOO}\.addons\.base\.models\.res_users: "
        rf"Password change for '(?P<user>[^']*)' \(#(?P<uid>\d+)\) "
        rf"from (?P<ip>\S+)",
        # Before 14.0 nothing is logged at INFO; this is emoi's fallback and
        # needs `log_handler = odoo.api:DEBUG`. It names the wizard, never who
        # changed whose password — hence a fallback, not the source.
        rf"{HEAD}{ODOO}\.api: call "
        rf"(?P<model>change\.password\.\w+|res\.users)\([^)]*\)\."
        rf"(?P<event>write|create|change_password\w*)",
    ],
    # werkzeug's access line carries Odoo's perf_info suffix
    # (query_count query_time remaining_time) from 12.0 on — at INFO, so no
    # special handler is needed. Older versions stop after the status.
    "calls": [
        rf"{HEAD}werkzeug: (?P<ip>\S+) - - \[[^\]]*\] "
        rf'"(?P<verb>[A-Z]+) (?P<route>\S+) [^"]*" (?P<status>\d+) \S+'
        rf"(?: (?P<queries>\d+) (?P<query_time>[\d.]+) (?P<other_time>[\d.]+))?",
    ],
    # Not here: `queue_job.job`, the logger emoi reads. It only logs
    # enqueueing, on every version 10.0 through 19.0, so it says nothing about
    # a run — no corpus sampled has a line from it, nor do emoi's own fixtures.
    "jobs": [
        # jobrunner lifecycle: starting, runner ready, Configured channel,
        # asking Odoo to run job <uuid> on db <db>, graceful stop, stopped.
        # `.channels` also lands here: job <uuid> marked done/running/failed
        # in channel root(C:1,Q:0,R:0,F:24)
        rf"{HEAD}{ODOO}\.addons\.queue_job\.jobrunner(?:\.\w+)?: "
        rf"(?P<event>.*?)\s*$",
        # The controller that runs a job is what logs its lifecycle, at DEBUG,
        # 10.0 through 19.0 — `%s` is Job.__repr__:
        # <Job 553d4994-…, priority:10> started | done | postponed
        # | OperationalError, postponed | enqueue depends started | … done
        rf"{HEAD}{ODOO}\.addons\.(?:connector|queue_job)\.controllers\.main: "
        rf"<Job (?P<job>[0-9a-f-]+), priority:(?P<priority>\d+)> (?P<event>.*?)\s*$",
    ],
    "workers": [
        # Worker WorkerHTTP (384363) alive
        rf"{HEAD}{ODOO}\.service\.server: Worker (?P<kind>Worker\w+) "
        rf"\((?P<worker>\d+)\) (?P<event>.*?)\s*$",
        # 10.0-15.0, DEBUG: WorkerCron (8464) <db> time:2.386s mem: Xk -> Yk
        # (diff: Zk). The only worker line carrying a duration, and the only
        # one naming the database it ran for; `server.py` drops it after 15.0.
        rf"{HEAD}{ODOO}\.service\.server: (?P<kind>WorkerCron) "
        rf"\((?P<worker>\d+)\) (?P<alt_db>\S+) (?P<event>time:[\d.]+s.*?)\s*$",
        # WorkerCron (2832690) timeout after 3600s
        # WorkerCron (853077) polling for jobs
        rf"{HEAD}{ODOO}\.service\.server: (?P<kind>Worker\w+) "
        rf"\((?P<worker>\d+)\) (?P<event>.*?)\s*$",
        # Worker (13284) exiting. request_count: 8192, registry count: 1.
        # Worker (4058) Exception occured, exiting...
        # Worker (15946) virtual memory limit (2048MB) reached
        rf"{HEAD}{ODOO}\.service\.server: Worker \((?P<worker>\d+)\) "
        rf"(?P<event>.*?)\s*$",
    ],
}

PATTERNS: dict[str, list[re.Pattern[str]]] = {
    name: [re.compile(source) for source in sources] for name, sources in _SOURCES.items()
}

# Patterns within a command capture different groups (only 18.0 logs a cron id,
# only a named worker has a kind). Rows are padded to the union so a command
# emits one shape whichever wording matched.
FIELDS: dict[str, list[str]] = {
    name: sorted({group for regex in regexes for group in regex.groupindex}) for name, regexes in PATTERNS.items()
}

# Every row also carries the head fields: time, pid, level, db, path.
COLUMNS: dict[str, list[str]] = {
    "crons": ["time", "db", "cron", "cron_id", "event", "duration"],
    "logins": ["time", "db", "user", "ip"],
    "passwords": ["time", "db", "user", "uid", "by", "ip", "event"],
    "jobs": ["time", "db", "job", "priority", "event"],
    "workers": ["time", "db", "kind", "worker", "event", "duration"],
    "calls": ["time", "db", "endpoint", "status", "queries", "total", "query_time"],
}

# Aggregated view of `calls`, keyed on the endpoint.
CALL_STATS = ["endpoint", "count", "t_total", "t_avg", "t_min", "t_max", "t_median", "q_avg"]

# `--split` breaks t_avg into its two halves — mean SQL time and mean non-SQL
# time
_BEFORE_Q = CALL_STATS.index("q_avg")
CALL_SPLIT = [*CALL_STATS[:_BEFORE_Q], "t_sql", "t_py", *CALL_STATS[_BEFORE_Q:]]

# Aggregated view of `crons`, keyed on the cron name. emoi reports memory
# alongside these; its source line (`http.py`'s `mem: Xk -> Yk (diff: Zk)`)
# was dropped after 15.0 and always needed a DEBUG handler, so it is not
# ported — the columns would be empty on every supported version.
# seealso: https://github.com/odoo/odoo/pull/78857/changes#diff-b4207a4658979fdb11f2f2fa0277f483b4e81ba59ed67a5e84ee260d5837ef6dL1159
CRON_STATS = ["cron", "count", "t_total", "t_avg", "t_min", "t_max"]

# Aggregated view of `workers`, keyed on the pid. emoi's `workers_stat` calls
# `first`/`last` dob/dod, and reports memory beside them — that is the `mem:`
# half of the one worker line carrying a duration, dead after 15.0, so only
# the timing half is here and it is empty on 16.0 and later.
WORKER_STATS = ["worker", "kind", "count", "first", "last", "t_total", "t_avg", "t_min", "t_max"]

# Aggregated view of `logins`, keyed on the login name alone — emoi does the
# same, and `-d` is how you split one login across databases when that matters.
# avg/min/max are logins per day, so `days` is what they average over.
USER_STATS = ["user", "count", "avg", "min", "max", "days", "first", "last"]

# Aggregated view of `calls` keyed on what the request was for, not which
# endpoint served it. emoi's three counters (common.authenticate, web/dataset,
# get_session_info) read routes only an RPC client still hits; these ask the
# same question — is anyone using this instance, and for what — of routes a
# current web client uses. First match wins, unmatched is `other`.
USAGE_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(source))
    for name, source in (
        ("login", r"/web/(?:login|session/authenticate)"),
        ("rpc", r"(?:/jsonrpc|/xmlrpc|/web/dataset/call_)"),
        # queue_job runs each job through this route, on every version.
        ("job", JOB_ROUTE),
        ("poll", r"(?:/longpolling/poll|/websocket|/bus/)"),
        ("static", r"/web/(?:assets|image|binary|content)"),
        ("report", r"/report/"),
    )
]
USAGE_STATS = ["type", "count"]

# `--check-activity`: traffic over time, whatever it was for.
ACTIVITY_STATS = ["period", "count"]
