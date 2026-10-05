# CHANGELOG

<!-- version list -->

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
