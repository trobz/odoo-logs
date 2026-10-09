# CHANGELOG

<!-- version list -->

## v0.5.0 (2026-10-09)

### Features

- Read Odoo 19.0 logs
  ([`de6d64f`](https://github.com/trobz/odoo-logs/commit/de6d64fea161371104b9a2573aa89b35061adc2c))


## v0.4.0 (2026-10-08)

### Bug Fixes

- Decode the 18.0 bad-query bytes repr before squashing
  ([`f15eda7`](https://github.com/trobz/odoo-logs/commit/f15eda76215a3ee5e4f1ff7ed52b2859efff8c0c))

- Group errors that differ only by embedded data
  ([`1652ee4`](https://github.com/trobz/odoo-logs/commit/1652ee4ad44405cb98875251e62235e2b35a9e4f))

- Group rejected INSERTs by table, not by the columns they set
  ([`73a0ddb`](https://github.com/trobz/odoo-logs/commit/73a0ddb0f40cd721f5295e1cb0d9ab5eb53ad5cc))

### Features

- Truncate long errors in the errors table
  ([`ff54b1f`](https://github.com/trobz/odoo-logs/commit/ff54b1f8c3310426acb00865303eedac10177b23))


## v0.3.0 (2026-10-07)

### Bug Fixes

- **mail-errors**: Use the block reader in the CLI, read both repr orders
  ([`f7e14d4`](https://github.com/trobz/odoo-logs/commit/f7e14d4b72a9b980c94e965bd6a929fc9bd64adb))

### Features

- Add mail-errors command for refused and failed sends
  ([`4312d47`](https://github.com/trobz/odoo-logs/commit/4312d47f507aab8117790de161d3890edcd9787e))

- **mail-errors**: Read mail.mail failures as blocks, catch dropped connections
  ([`19b716a`](https://github.com/trobz/odoo-logs/commit/19b716a3dede70a8920a19ad8cf7aefda7a5071c))


## v0.2.0 (2026-10-05)

### Bug Fixes

- Bring dated rotations (server.log-<date>-<epoch>) along with a base logfile
  ([`cd2a453`](https://github.com/trobz/odoo-logs/commit/cd2a4530556001e075796e7dd5ce7bb5fbab90b5))

- Only echo the window on stderr when one was given
  ([`cd666de`](https://github.com/trobz/odoo-logs/commit/cd666de9817458f82b9f0d06a64f43e97012d507))

- Save the list cache after each archive, not once at the end
  ([`201c28e`](https://github.com/trobz/odoo-logs/commit/201c28e52f7775fc9c67d31c1bd043dab91a9c91))

### Features

- Add list command showing the period each log file covers
  ([`061447a`](https://github.com/trobz/odoo-logs/commit/061447af4be136d8718373948cfad9245d657acc))


## v0.1.2 (2026-09-25)

### Bug Fixes

- Keep lines with no database under -d
  ([`d596b07`](https://github.com/trobz/odoo-logs/commit/d596b0788321334c184d0476b626ba7187dd0cf0))


## v0.1.1 (2026-09-11)

### Bug Fixes

- Keep 0.000s requests in timing stats
  ([`fd0bb25`](https://github.com/trobz/odoo-logs/commit/fd0bb253517e88192b4d6a2f0086973893fee4fb))

- Make a bare date on --to cover the whole day
  ([`627c484`](https://github.com/trobz/odoo-logs/commit/627c484dc122a73ff9dd6bd6bebfe9c0382db00c))

- Render table cells as plain text, not Rich markup
  ([`4982f14`](https://github.com/trobz/odoo-logs/commit/4982f1432535783695760c3e2b7c0fe13940d63c))


## v0.1.0 (2026-08-20)

- Initial Release

## v0.0.0 (2026-08-17)

- Initial Release
