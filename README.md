# odoo-logs

Prefiltered, structured data out of Odoo server logs — so you don't grep them
by hand, and so an MCP client can consume them. Reads plain and gzipped logs
from 9.0 through 18.0.

## Installation

```bash
uv tool install git+https://github.com/trobz/odoo-logs
```

Or for development:

```bash
git clone https://github.com/trobz/odoo-logs
cd odoo-logs
make install                       # install deps + pre-commit hooks
uv tool install --editable .       # make `odoo-logs` available globally
```

```
make check     # lint, format, type-check
make test      # pytest
```

Other tasks: regenerate the CLI reference with
`uv run typer odoo_logs.main utils docs --name odoo-logs --output CLI.md`.

## Commands

See **[CLI.md](CLI.md)** — generated from the code, the source of truth — or
`odoo-logs <command> --help` for every command and flag.

**[CHECKLIST.md](CHECKLIST.md)** tracks the port from `emoi logs`: every emoi
command and option, what it maps to here, and what is deliberately skipped.

Log files are positional, so the shell does the globbing, and global options
come *before* the command:

```bash
odoo-logs errors server.log server.log.*.gz
odoo-logs --output-format json crons /var/log/odoo/*.log
odoo-logs --from 2026-08-01 --database prod logins server.log
odoo-logs --period 'last week' calls server.log --check-activity
```

`--period` takes the range in words — `today`, `yesterday`, `3 days ago`,
`this week`, `last month` — and is nothing more than `--from`/`--to` worked
out for you.

Naming no window at all reads the whole of every file given, which is the one
default that can't hide a line from a file you named. When that covers a lot,
the span you just read is reported on stderr so it is at least visible:

```
$ odoo-logs calls /var/log/odoo/server.log*
<table>
Read 4636 entries spanning 2026-06-01 to 2026-08-17; -p today or -p 'this week' narrows it.
```

It is advice, not a filter — nothing is dropped, and a small log stays quiet.

Five behaviours the flag list can't express:

**`calls` reads werkzeug's access line**, not a DEBUG handler. Odoo appends
`query_count query_time remaining_time` to it from 12.0 on, at INFO, so
request timings are available on a default-configured instance:

```
$ odoo-logs calls server.log -n 3
endpoint                          count  t_total  t_avg  t_max  q_avg
/tuico_api/static/…/icon.png          2    1.231  0.615  1.097   73.5
res.config.settings.get_views         2    1.063  0.531  0.583  443
/websocket                           49    0.844  0.017  0.026    5.5
```

Only `call_kw` / `call_button` routes carry a real model and method, and
those key as `model.method`. Every other route keys on its path with record
ids collapsed (`/web/image/res.partner/3/avatar_128?unique=…` →
`/web/image/res.partner/N/avatar_128`) so one endpoint doesn't fragment into
one row per record.

**`-a/--aggregate hour|day|week|month` turns a total into a trend.** Every
aggregating command takes it, and it adds a `period` column rather than
changing the ones already there:

```
$ odoo-logs calls server.log* -a day -e product.product -n 4
endpoint                        period      count  t_total  t_avg  t_max  q_avg
product.product.get_views       2026-07-01     12    2.350  0.196  0.511   85.8
product.product.web_search_read 2026-07-13     10    2.343  0.234  0.369   54.7
product.product.web_search_read 2026-06-08      5    2.200  0.440  0.559   28.2
product.product.web_search_read 2026-07-01      8    2.150  0.269  0.567   30.8
```

`calls --check-activity` drops the endpoint and counts traffic per period
instead; `usage` keeps the period and counts by what the request was *for*
(`rpc`, `login`, `job`, `poll`, `static`, `report`); `users` does the same for
logins, per user.

**`jobs --stats` times queue_job off the same access line.** Every job runs
through `/queue_job/runjob` — unchanged from 10.0 to 19.0 — so werkzeug times
a job exactly the way it times a request, no DEBUG handler needed:

```
$ odoo-logs jobs server.log* --stats -a day
endpoint           period      count  t_total  t_avg  t_min  t_max  q_avg
/queue_job/runjob  2026-06-08      5    2.157  0.431  0.048  1.542   67.6
```

The uuid in that route is unique per run, so there is nothing to aggregate on
it — `--aggregate` buckets by time instead. Without `--stats`, `jobs` lists
jobrunner lifecycle and per-job events; everything below the jobrunner is
logged at DEBUG on every version.

`workers --stats` is the same shape one level up: a row per pid, with its
first and last sighting and — on 15.0 and older, where `WorkerCron (N) <db>
time:2.386s` still exists — how long its runs took.

**`errors` groups by the exception raised**, so a log with 20k tracebacks
comes back as a handful of rows:

```
$ odoo-logs errors server.log.1 -n 3
type                 error                                    count  first  last
OSError              [Errno 98] Address already in use: (…)   19785  …      …
RuntimeError         Couldn't bind the websocket. (…)           286  …      …
odoo.service.server  WorkerHTTP (N) timeout after 3600s          18  …      …
```

A log entry runs from a timestamped line to the next one, so the traceback
below an error belongs to it. The pid inside parentheses is normalised to
`(N)` so one recurring failure doesn't split into one group per process.
Nothing is filtered by default — the usual noise filter is
`-x 'raise_exception=False' -x Loading`.

**Version coverage.** Loggers and messages get renamed between versions
(`base.ir.ir_cron` on 10.0/11.0, `base.models.ir_cron` after), so each command
matches every known wording. Patterns are backed by real lines in
`tests/sample.log`, captured from 9.0 through 18.0, and a test asserts every
pattern matches one — a wording that goes dead fails rather than quietly
returning nothing. The 10.0 and 17.0 cron wordings are the exception: no
corpus has one, so they are rendered from that version's own `_logger`
format string.

Two commands depend on a version floor rather than a wording:

- `calls` needs 12.0+ for the perf suffix. Older logs still parse — the row
  comes back with a status and no timing, and is left out of the aggregate.
- `passwords` reads `res_users`' INFO line, added in 14.0; 16.0 added the
  `by` half naming who made the change. Before 14.0 it falls back to
  `odoo.api`, which does need `log_handler = odoo.api:DEBUG`.

**Not ported from `emoi logs`:** per-call *memory* deltas
(`mem: Xk -> Yk (diff: Zk)`). That line was dropped from `odoo/http.py` after
15.0, and it always required `log_handler = odoo.http.rpc.response:DEBUG`.
The timing half of what `emoi logs calls` reported is covered by `calls`.
