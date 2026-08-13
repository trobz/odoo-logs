# Porting checklist — `emoi logs` → `odoo-logs`

Every `emoi logs` command and option, with its status here. `emoi/command/logs.py`
on `py3` is the source of truth for the left column.

Legend: **done** (same option, same behaviour) · **differs** (same option, our
behaviour or default is not emoi's — reason given) · **renamed** · **skip**
(deliberate, reason given) · **todo** (worth building, not built).

Three decisions run across commands, so they are not repeated per row:

- **`-n/--limit` defaults to 0, not 10.** emoi truncates to the top 10 unasked.
  Ours pipes into `--output-format json|csv`, where dropping rows silently is
  data loss rather than a screenful. Pass `-n 10` for emoi's view.
- **`-s/--sort` defaults to a total, not a mean** (`t_total` where emoi has
  `t_avg`, `count` where it has `avg`). A mean ranks a one-off slow call above
  an endpoint that eats an hour a day across 100k fast calls; the total answers
  "where does the time actually go". Pass `-s t_avg` for emoi's view.
- **`--save-cache` / `--from-cache` are not ported**, because the measurement
  said to spend the effort elsewhere. emoi pickles parsed rows so a second
  command need not re-parse. On a 67MB, 1.27M-line corpus here: six commands
  scanning separately, 6.49s; one pass gated by a single head-match prefilter,
  2.14s; a cache on top of that would save the remaining ~2.1s. The prefilter
  shipped — 3x for about fifteen lines and no new state — and the cache would
  buy a third as much in exchange for a file on disk, a staleness rule, and a
  flag on every command. Until a single pass is the bottleneck, one-time
  parsing is served by `--output-format json <cmd> ... > out.json`, which keeps
  staleness visible as a file you dated rather than hidden in a cache.

## Global options

`emoi logs <global> <command>` → `odoo-logs <global> <command>`.

| emoi | odoo-logs | Status |
|---|---|---|
| `-f/--from`, `-t/--to` | `-f/--from`, `-t/--to` | done |
| `--database` | `-d/--database` | done |
| `--period "2 days ago"` | `-p/--period` | differs — same grammar (`today`, `<n> <unit> ago`, `this`/`last week\|month\|year`). Anything outside it errors rather than being guessed at. emoi defaults to today when given no window; ours reads every file whole — emoi's range also picks which rotated files to open, while ours are named on argv, so a default could only subtract from what was asked for. A large unwindowed read reports its span on stderr instead |
| `--source PATH;PATH` | positional `LOGS...` | renamed — the shell globs, no separator to parse |
| `-v/--verbose` (flag, writes `/tmp/<generated>`) | `--verbose/--extract FILE` | renamed — takes the path instead of inventing one |
| `--output PATH` | `--output-file` | renamed |
| `--log-timezone` | — | skip — timestamps are read as written; no corpus needs a shift |
| `--regex` | — | skip — internal pattern selector, not a user knob |
| `--keep-log-filenames` | — | skip — artefact of emoi copying logs to `/tmp` first |
| `-r/--rsyslog` | — | **todo** — syslog-prefixed lines; every pattern here assumes Odoo's own format |
| `-i/--instances` | — | skip — emoi resolves instances from project config; this CLI takes files |

Ours with no emoi equivalent: `--output-format text\|json\|csv`, `--log-level`,
`-V/--version`.

## `calls` → `odoo-logs calls`

Different source line: emoi reads `odoo.http.rpc.response` at DEBUG, which
**`http.py` dropped after 15.0** — so `emoi logs calls` returns nothing on 16.0+.
Ours reads werkzeug's INFO access line (12.0+, default handler).

| emoi | odoo-logs | Status |
|---|---|---|
| `--limit` (10) | `-n/--limit` (0) | differs — see above |
| `--sort` (t_avg) | `-s/--sort` (t_total) | differs — see above |
| `--min-count` | `--min-count` | done |
| `--gt SECONDS` | `--gt SECONDS` | done — with `--verbose` it is emoi's slow-call export |
| `--aggregate hour/day/week/month` | `-a/--aggregate` | differs — same buckets, but weeks are ISO and carry their year (`2026-W34`); emoi's `week 33` folds that week of every year into one row |
| `--check-activity` | `--check-activity` | differs — counts untimed requests too, since the question is traffic, not duration. Implies `--aggregate day` |
| `--method` | `-e/--endpoint REGEX` | renamed — regex, and ours keys on the route |
| `--output csv` | `--output-format csv` | renamed (global) |
| `--output prometheus`, `--output-file` | — | **todo** — only if something scrapes it |
| `--save-cache` / `--from-cache` | — | skip — see the cache note above |
| `--output-type` | — | skip — duplicate of `--output` in emoi itself |

Columns — emoi: `method period count t_avg t_min t_max t_median t_total
m_avg m_min m_max m_median`.

| emoi | odoo-logs | Status |
|---|---|---|
| method | endpoint | differs — route-keyed, see blind spot below |
| count, t_avg, t_min, t_max, t_median, t_total | same | done |
| period | period | done — with `--aggregate` |
| m_avg/m_min/m_max/m_median | — | skip — same dead `mem:` line, gone after 15.0 |
| — | `q_avg` | ours only — emoi's source carries no query count |
| — | `t_sql`, `t_py` (`--split`) | ours only — the two halves of `t_avg` |

**Known blind spot:** emoi keyed on the RPC object+method, so `/jsonrpc` and
`/xmlrpc/2/object` traffic broke down per model. We key on the HTTP route, so
all integration traffic collapses into one row. `call_kw` is unaffected.

## `crons` → `odoo-logs crons`

| emoi | odoo-logs | Status |
|---|---|---|
| `--limit` (10) | `-n/--limit` (0) | differs — see above |
| `--sort` (t_avg) | `-s/--sort` (t_total) | differs — see above |
| aggregate-by-default | same | done |
| `m_avg/m_min/m_max` | — | skip — same dead `mem:` line |
| — | `--events` | ours only — per-event rows: starts, failures, timeouts |
| — | `t_total` | ours only |

Source also differs: emoi reads only the DEBUG timing line, so it sees nothing
on a default handler. Ours reads the INFO `done in`/`Job done:` lines too, and
resolves the INFO/DEBUG duplicate per `(db, pid, cron)`.

`--aggregate` is not offered here — emoi has none on `crons` either, and a cron
is already its own schedule.

## `errors` → `odoo-logs errors`

| emoi | odoo-logs | Status |
|---|---|---|
| `--output csv` | `--output-format csv` | renamed (global) |
| `-v` full dump to `/tmp` | `--verbose FILE` (global) | done — whole entry, traceback included |
| `--ignore "Type.*msg,Type2.*"` | `-x/--exclude REGEX` (repeatable) | renamed — more general |
| `-c/--context cron/job/http/any` | `-l/--logger REGEX` | renamed — emoi's map was hardcoded |
| traceback-only, always | `--traceback-only` (opt-in) | differs — see below |
| `--monitoring` (`.trobz/monitoring.yml`) | — | skip — project-bound; this CLI takes files |
| — | `-n/--limit` | ours only |
| — | `first`/`last` columns | ours only |

**The divergence:** emoi drops every entry without a traceback, so
`Model x.y has no table.` never reaches its counts. Ours keeps them and makes
the filter opt-in, which is why totals disagree. Ours looks right; flipping the
default is a one-line change if parity matters more.

## `users` → `odoo-logs users`

| emoi | odoo-logs | Status |
|---|---|---|
| `--limit` (10) | `-n/--limit` (0) | differs — see above |
| `--sort` (avg) | `-s/--sort` (count) | differs — see above |
| `--aggregate hour/day/month` | `-a/--aggregate` (also `week`) | done |
| `period`, `user`, `count`, `avg`, `min`, `max` | same | done — avg/min/max are logins per day, as in emoi |
| `used_days` | `days` | renamed |
| `min_login_date` / `max_login_date` | `first` / `last` | differs — emoi reports the date of the quietest and busiest day; ours the first and last login, which is what those column names read as |
| source: 9.0/10.0's `successful login from` only | every wording `logins` knows | differs — 9.0 through 18.0, so a modern instance is not silently empty |
| `--verbose` second table (user, count, last_day) | — | skip — that *is* the main table once `--aggregate` is off |

## `usage` → `odoo-logs usage`

| emoi | odoo-logs | Status |
|---|---|---|
| `--sort` (period) | `-s/--sort` (count) | differs — see above |
| `--aggregate hour/day/month` | `-a/--aggregate` (also `week`) | done |
| `type`, `period`, `count` | same | done |
| — | `-n/--limit` | ours only |
| type = `dataset` / `authenticate` / `get_session_info` | `rpc` / `login` / `job` / `poll` / `static` / `report` / `other` | differs — emoi's three read `common.authenticate` and `/web/session/get_session_info`, routes only an RPC client still hits. Ours classify werkzeug's access line, so a current web client is visible |

## `jobs` → `odoo-logs jobs`

emoi reports queue_job **statistics**; ours defaults to jobrunner lifecycle and
per-job **events**, with `--stats` for the timings.

| emoi | odoo-logs | Status |
|---|---|---|
| per-job timing stats | `--stats` | differs — different source, see below |
| `--limit` (10) | `-n/--limit` (0) | differs — see above |
| `--sort` (t_avg) | `-s/--sort` (t_total) | differs — see above |
| `--aggregate` | `-a/--aggregate` | done — with `--stats` |
| `--output csv` | `--output-format csv` | renamed (global) |
| `--method` | — | skip — nothing in the route, and no line in any corpus sampled, names a job's method |
| — | event rows (default view) | ours only |
| — | `--stats` job `priority` on event rows | ours only |

**Different source, and it decides the rest.** emoi reads
`queue_job.job: <method>: <uuid> time:Xs mem:…` at DEBUG. That logger emits
nothing per run on any version 10.0–19.0 — they all log the run from
`queue_job.controllers.main` — and neither our corpora nor emoi's own py2
fixtures hold a line from it, so it is not in the pattern table at all.

queue_job runs every job through `/queue_job/runjob`, unchanged 10.0 through
19.0, so werkzeug's access line times a job the way it times a request — at
INFO, with the perf triplet from 12.0 on. `--stats` reads that, which is why
it needs no DEBUG handler and why 11.0's job runs come back untimed.

The uuid in that route is unique per run, so keying on it would produce one
row per job with nothing aggregated — hence no `--method` equivalent and no
uuid grouping. `--aggregate` buckets by time instead: throughput and cost per
hour or day, which is what emoi's `--aggregate` answered.

Per-job **events** (`started`, `done`, `postponed`, `enqueue depends …`, and
the jobrunner's `job <uuid> marked done in channel …`) are corpus-verified as
of 16.0 and read on the default `jobs` view. They are DEBUG-only on every
version, so a default handler shows the jobrunner lifecycle and nothing else.

## `workers_stat` → `odoo-logs workers --stats`

emoi reports one row per worker; ours defaults to worker births, deaths,
timeouts and limit hits, with `--stats` for the per-worker rollup.

| emoi | odoo-logs | Status |
|---|---|---|
| one row per worker | `--stats` | done |
| `count` | `count` | differs — every event for that pid, not just its timed runs |
| `dob` / `dod` | `first` / `last` | renamed — first and last time the pid is seen at all |
| `--sort` (m_avg) | `-s/--sort` (count) | differs — the column emoi sorts by does not exist here |
| `--min-count` | — | skip — `-n/--limit` on a count-sorted table does the same job |
| `--from-cache` | — | skip — see the cache note above |
| `m_avg`/`m_min`/`m_max` | — | skip — see below |
| — | `t_total`/`t_avg`/`t_min`/`t_max` | ours only |
| — | `-a/--aggregate` | ours only |
| — | event rows (default view, with `duration`) | ours only |

**One line carries both halves.** `WorkerCron (8464) <db> time:2.386s mem:
1659524k -> 1657988k (diff: -1536k)` is the only worker line with a duration
on it and the only one naming the database the run was for. `server.py` drops
it after 15.0, so the `t_` columns are empty on 16.0 and later, and the memory
half is not ported for the same reason it is not ported anywhere else — it
would be a column that is always blank on a supported version.

## Not ported at all

| emoi | Status |
|---|---|
| `crons_history --graph life` | skip — plotly HTML timeline + pickle cache; `--output-format json` feeds any plotter |
| `workers_history --graph life/mem` | skip — same, plus the dead memory source |

## Ours with no emoi counterpart

| Command | Note |
|---|---|
| `logins` | who logged in, which db, from where — 10.0 through 18.0 wordings |
| `passwords` | password changes: whose, by whom, from where — INFO from 14.0, `odoo.api` DEBUG before |

## Suggested order

1. `-r/--rsyslog` — only if logs actually arrive syslog-prefixed.
2. Job events on a default handler — everything below the jobrunner is DEBUG
   on every version, so `jobs` is thin unless the instance is configured for
   it. Nothing to build until it is known whether that is worth asking for.
