"""Corpus fixture: one sample log, delivered every way a real one arrives.

`sample.log` holds real lines captured from 9.0 through 18.0 instances — one
per wording each command must recognise, and `test_every_pattern_has_a_line`
holds it to that, since a pattern with no line is one nobody would notice
going dead. Database names, logins, cron names and paths are anonymised to
`odoo9` … `odoo18`; the message shapes the patterns key on are untouched. The
9.0 lines come from emoi's own py2 fixtures, the oldest corpus reachable.

Cron failures and the 10.0/17.0 wordings are the exception: no corpus sampled
has one, so those lines are rendered from the version's own `_logger` format
string in `odoo/addons/base/*/ir_cron.py` and marked `odoo10` / `odoo17`.

Every command test consumes `logs`, so adding a command checks it against
every delivery and adding a delivery checks it against every command.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

SAMPLE = Path(__file__).parent / "sample.log"


@pytest.fixture(params=["plain", "gzip", "split"])
def logs(request, tmp_path: Path) -> list[Path]:
    """The sample log as the CLI would be handed it."""
    lines = SAMPLE.read_text().splitlines(keepends=True)

    if request.param == "plain":
        return [SAMPLE]

    if request.param == "gzip":
        packed = tmp_path / "server.log.1.gz"
        with SAMPLE.open("rb") as src, gzip.open(packed, "wb") as dst:
            shutil.copyfileobj(src, dst)
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
