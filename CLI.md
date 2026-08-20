# `odoo-logs`

Prefiltered data out of Odoo server logs.

**Usage**:

```console
$ odoo-logs [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `-V, --version`
* `--output-file <str>`: [default: -]
* `--output-format <str>`: One of: text, json, csv.  [default: text]
* `-f, --from <str>`: Only entries at or after YYYY-MM-DD[ HH:MM:SS].
* `-t, --to <str>`: Only entries at or before YYYY-MM-DD[ HH:MM:SS].
* `-p, --period <str>`: A range in words: today, yesterday, &#x27;3 days ago&#x27;, &#x27;this week&#x27;, &#x27;last month&#x27;. --from/--to override their end of it.
* `-d, --database <str>`: Only entries for this database.
* `--verbose, --extract FILE`: Also write the raw log lines behind the output to FILE, readable without the server&#x27;s logs.
* `--log-level <str>`: [default: WARNING]
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `crons`: Cron timings, aggregated per cron job...
* `logins`: Successful logins: who, which database,...
* `users`: Login activity per user: how often, over...
* `usage`: What the instance&#x27;s traffic was for:...
* `passwords`: Password changes: whose password, changed...
* `jobs`: queue_job runner lifecycle and per-job...
* `workers`: Worker births, deaths, timeouts and...
* `calls`: Request timings from werkzeug&#x27;s access...
* `errors`: ERROR and CRITICAL entries, grouped by...

## `odoo-logs crons`

Cron timings, aggregated per cron job (ir_cron).

Only runs that logged a duration can be aggregated: 17.0 and 18.0 log one
at INFO, older versions only under `log_handler = &lt;ir_cron logger&gt;:DEBUG`.
`--events` shows every event instead, including the ones that carry no
timing — starts, failures and timeouts.

**Usage**:

```console
$ odoo-logs crons [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `-s, --sort <str>`: One of: count, t_total, t_avg, t_min, t_max.  [default: t_total]
* `--events`: One row per event, not per cron: starts, failures, timeouts.
* `--help`: Show this message and exit.

## `odoo-logs logins`

Successful logins: who, which database, from where.

**Usage**:

```console
$ odoo-logs logins [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `--help`: Show this message and exit.

## `odoo-logs users`

Login activity per user: how often, over how many days.

emoi&#x27;s `users`, off the same lines as `logins` — so every version&#x27;s
wording counts, not just 10.0&#x27;s. `avg`, `min` and `max` are logins per
day and `days` is how many days the user appeared at all, so a user with
one login a day for a week reads differently from one with seven in an
afternoon.

**Usage**:

```console
$ odoo-logs users [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `-s, --sort <str>`: One of: period, count, avg, min, max, days, first, last (period needs --aggregate).  [default: count]
* `-a, --aggregate <str>`: Bucket the stats by period: hour, day, week, month.
* `--help`: Show this message and exit.

## `odoo-logs usage`

What the instance&#x27;s traffic was for: logins, rpc, polling, static.

emoi&#x27;s `usage`. Its counters read `common.authenticate` and
`/web/session/get_session_info`, which only an RPC client still hits;
these classify werkzeug&#x27;s access line instead, so a current web client
is visible too. `--aggregate` is what makes it a trend rather than a
total.

**Usage**:

```console
$ odoo-logs usage [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `-s, --sort <str>`: One of: period, count (period needs --aggregate).  [default: count]
* `-a, --aggregate <str>`: Bucket the stats by period: hour, day, week, month.
* `--help`: Show this message and exit.

## `odoo-logs passwords`

Password changes: whose password, changed by whom, from where.

Logged at INFO by res_users from 14.0 on; 16.0 added the `by` half.
Before 14.0 this falls back to odoo.api, which needs a DEBUG handler.

**Usage**:

```console
$ odoo-logs passwords [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `--help`: Show this message and exit.

## `odoo-logs jobs`

queue_job runner lifecycle and per-job events.

`--stats` reports timings instead. queue_job runs every job through
`/queue_job/runjob`, so werkzeug&#x27;s access line carries a job&#x27;s duration
and query count exactly the way it carries a request&#x27;s — at INFO, 12.0
on, no DEBUG handler, which is what `calls` reads.

emoi keys its job stats on the method; nothing in that route or in any
log line sampled names one, and the uuid it does carry is unique per run,
so there is nothing to aggregate on it. `--aggregate` buckets by time
instead — jobs per hour and what each cost, which is the throughput
question emoi&#x27;s own `--aggregate` answered.

**Usage**:

```console
$ odoo-logs jobs [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `--stats`: How long job runs took, instead of what happened.
* `-s, --sort <str>`: One of: period, count, t_total, t_avg, t_min, t_max, t_median, q_avg (period needs --aggregate).  [default: t_total]
* `-a, --aggregate <str>`: Bucket the stats by period: hour, day, week, month.
* `--help`: Show this message and exit.

## `odoo-logs workers`

Worker births, deaths, timeouts and resource limits.

`--stats` is emoi&#x27;s `workers_stat`: one row per pid, with its `dob`/`dod`
as `first`/`last`. The `t_` columns come from `WorkerCron (N) &lt;db&gt;
time:2.386s`, the only worker line carrying a duration — `server.py`
drops it after 15.0, so they are empty on 16.0 and later.

**Usage**:

```console
$ odoo-logs workers [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `--stats`: One row per worker instead of one per event.
* `-s, --sort <str>`: One of: period, kind, count, first, last, t_total, t_avg, t_min, t_max (period needs --aggregate).  [default: count]
* `-a, --aggregate <str>`: Bucket the stats by period: hour, day, week, month.
* `--help`: Show this message and exit.

## `odoo-logs calls`

Request timings from werkzeug&#x27;s access line, grouped by endpoint.

Needs Odoo 12.0+, which appends `query_count query_time remaining_time`
to that line. It is logged at INFO, so no special handler is required.

`--gt` with `--verbose` is emoi&#x27;s slow-call export: the raw log lines of
every request over the threshold, extracted to a file.

Times are wall time. `--split` breaks t_avg into t_sql + t_py, which is
the difference between an endpoint the database is slowing down and one
the code is.

`--aggregate` splits each endpoint per hour/day/week/month;
`--check-activity` drops the endpoint and just counts traffic over time.

**Usage**:

```console
$ odoo-logs calls [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `-s, --sort <str>`: One of: period, count, t_total, t_avg, t_min, t_max, t_median, t_sql, t_py, q_avg (period needs --aggregate).  [default: t_total]
* `-e, --endpoint <str>`: Only endpoints matching this regex.
* `--gt <float>`: Only requests slower than this many seconds.  [default: 0]
* `--min-count <int>`: Drop endpoints called fewer than this many times.  [default: 0]
* `--split`: Add t_sql and t_py, the two halves of t_avg.
* `-a, --aggregate <str>`: Bucket the stats by period: hour, day, week, month.
* `--check-activity`: Requests per period instead of per endpoint; implies --aggregate day.
* `--help`: Show this message and exit.

## `odoo-logs errors`

ERROR and CRITICAL entries, grouped by exception type and message.

`--logger` is the general form of emoi&#x27;s `-c cron/job/http`: those are
just the ir_cron, queue_job and werkzeug loggers.

**Usage**:

```console
$ odoo-logs errors [OPTIONS] {LOGS...}
```

**Arguments**:

* `LOGS...`: Log files to read; plain or gzipped (server.log server.log.*.gz).  [required]

**Options**:

* `-n, --limit <int>`: Max rows; 0 for all.  [default: 0]
* `-x, --exclude <str>`: Drop entries matching this regex; repeatable. Common noise: -x &#x27;raise_exception=False&#x27; -x Loading
* `-l, --logger <str>`: Only entries whose logger matches this regex: -l ir_cron, -l &#x27;queue_job|werkzeug&#x27;.
* `--traceback-only`: Only entries carrying a traceback.
* `--help`: Show this message and exit.
