"""Corpus fixture: the sample logs, delivered every way a real one arrives.

`samples/<version>.log` holds real lines captured from that version's
instances — one per wording each command must recognise, and
`test_every_pattern_has_a_line` holds them to that, since a pattern with no
line is one nobody would notice going dead. The fixture reads every version
as one corpus, so each command is still checked against all of them.
Database names, logins, cron names and paths are anonymised to `odoo9` …
`odoo18`; the message shapes the patterns key on are untouched. The 9.0 lines
come from emoi's own py2 fixtures, the oldest corpus reachable.

A line logged outside a database (`?`, `None`) sits in the version its own
text points to: the db its message names, the pid of a line whose db is
known, or the job it reports on.

Cron failures and the 10.0/17.0 wordings are the exception: no corpus sampled
has one, so those lines are rendered from the version's own `_logger` format
string in `odoo/addons/base/*/ir_cron.py` and marked `odoo10` / `odoo17`.

Every command test consumes `logs`, so adding a command checks it against
every delivery and adding a delivery checks it against every command.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

# Oldest first, by version number rather than by name (9.0 before 10.0).
SAMPLES = sorted(
    (Path(__file__).parent / "samples").glob("*.log"),
    key=lambda path: tuple(int(part) for part in path.stem.split(".")),
)


@pytest.fixture(params=["plain", "gzip", "split"])
def logs(request, tmp_path: Path) -> list[Path]:
    """The sample logs as the CLI would be handed them."""
    lines = [line for sample in SAMPLES for line in sample.read_text().splitlines(keepends=True)]

    if request.param == "plain":
        return SAMPLES

    if request.param == "gzip":
        packed = tmp_path / "server.log.1.gz"
        with gzip.open(packed, "wt") as fh:
            fh.writelines(lines)
        return [packed]

    # Rotation splits one stream across files, newest first, some gzipped —
    # results must come back in time order regardless of argument order.
    # Cut on an entry boundary; rotation never splits a traceback from its head.
    half = next(i for i, line in enumerate(lines) if i >= len(lines) // 2 and line[:4].isdigit())
    old = tmp_path / "server.log.2.gz"
    with gzip.open(old, "wt") as fh:
        fh.writelines(lines[:half])
    new = tmp_path / "server.log"
    new.write_text("".join(lines[half:]))

    return [new, old]
