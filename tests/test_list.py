"""`list`: which file holds which period, without parsing a log."""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from odoo_logs import main, parse

runner = CliRunner()


@pytest.fixture(autouse=True)
def cache_home(tmp_path_factory, monkeypatch) -> Path:
    """`list` remembers what it learned from archives; keep that off the real home."""
    home = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(home))

    return home


HEAD = "{day} {time},123 100 INFO db odoo.service: {text}\n"
TRACEBACK = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: boom\n"


def entries(day: str, first: str, last: str) -> str:
    """Two entries, a traceback under the last one, as a rotation leaves it."""
    return HEAD.format(day=day, time=first, text="first") + HEAD.format(day=day, time=last, text="last") + TRACEBACK


@pytest.fixture
def rotation(tmp_path: Path) -> Path:
    """A log directory the way a rotated instance leaves it: plain current
    file, gzipped history, and a lock file that is not a log."""
    (tmp_path / "server.log").write_text(entries("2026-09-26", "07:16:01", "09:00:00"))
    (tmp_path / "server.log.2026-09-25").write_text(entries("2026-09-25", "07:16:00", "23:59:59"))
    with gzip.open(tmp_path / "server.log.2026-09-24.gz", "wt") as fh:
        fh.write(entries("2026-09-24", "07:15:00", "22:00:00"))
    (tmp_path / "server.log_rotating_lock").write_text("")

    return tmp_path


def names(rows: list[dict]) -> list[str]:
    return [Path(row["path"]).name for row in rows]


def test_a_directory_lists_its_logs_oldest_first_and_skips_lock_files(rotation):
    found = parse.survey([rotation])

    assert names(found) == ["server.log.2026-09-24.gz", "server.log.2026-09-25", "server.log"]


def test_a_period_is_read_from_the_first_and_last_entry_heads(rotation):
    by_name = {Path(row["path"]).name: row for row in parse.survey([rotation])}

    # The last line of a plain file is a traceback: the end is the entry above it.
    assert by_name["server.log.2026-09-25"]["start"] == datetime(2026, 9, 25, 7, 16, 0, 123000)
    assert by_name["server.log.2026-09-25"]["end"] == datetime(2026, 9, 25, 23, 59, 59, 123000)


def test_gzipped_files_are_read_like_plain_ones(rotation):
    row = next(r for r in parse.survey([rotation]) if r["path"].endswith(".gz"))

    assert (row["start"], row["end"]) == (
        datetime(2026, 9, 24, 7, 15, 0, 123000),
        datetime(2026, 9, 24, 22, 0, 0, 123000),
    )
    assert row["note"] == "gz"
    assert row["size"] == Path(row["path"]).stat().st_size  # on-disk size, not inflated


def test_a_base_logfile_stands_for_its_whole_rotation(rotation):
    found = parse.survey([rotation / "server.log"])

    assert names(found) == ["server.log.2026-09-24.gz", "server.log.2026-09-25", "server.log"]


def test_any_other_file_stands_for_itself(rotation):
    assert names(parse.survey([rotation / "server.log.2026-09-25"])) == ["server.log.2026-09-25"]


def test_a_tail_longer_than_one_chunk_is_still_found(tmp_path, monkeypatch):
    monkeypatch.setattr(parse, "TAIL_CHUNK", 64)
    log = tmp_path / "server.log"
    log.write_text(entries("2026-09-25", "07:00:00", "08:00:00") + TRACEBACK * 20)

    assert parse.survey([log])[0]["end"] == datetime(2026, 9, 25, 8, 0, 0, 123000)


def test_a_window_keeps_only_the_files_a_scan_would_read(rotation):
    found = parse.survey([rotation], since=datetime(2026, 9, 25, 19, 50), until=datetime(2026, 9, 25, 20, 10))

    assert names(found) == ["server.log.2026-09-25"]


def test_a_window_spanning_a_rotation_keeps_both_sides(rotation):
    found = parse.survey([rotation], since=datetime(2026, 9, 25, 23, 0), until=datetime(2026, 9, 26, 8, 0))

    assert names(found) == ["server.log.2026-09-25", "server.log"]


def test_overlapping_files_are_flagged(tmp_path):
    (tmp_path / "server.log.1").write_text(entries("2026-09-25", "07:00:00", "12:00:00"))
    (tmp_path / "server.log").write_text(entries("2026-09-25", "10:00:00", "13:00:00"))

    notes = {Path(row["path"]).name: row["note"] for row in parse.survey([tmp_path])}

    assert notes == {"server.log.1": "", "server.log": "overlaps previous"}


def test_a_truncated_archive_keeps_what_it_held(tmp_path):
    packed = tmp_path / "server.log.1.gz"
    with gzip.open(packed, "wt") as fh:
        fh.write(entries("2026-09-25", "07:00:00", "12:00:00") * 2000)
    packed.write_bytes(packed.read_bytes()[:-200])

    row = parse.survey([packed])[0]

    assert row["start"] == datetime(2026, 9, 25, 7, 0, 0, 123000)
    assert row["note"] == "gz, truncated"


def test_files_without_entries_are_listed_but_say_why(tmp_path):
    (tmp_path / "server.log").write_text("")
    (tmp_path / "server.log.1").write_text(TRACEBACK)

    notes = {Path(row["path"]).name: row["note"] for row in parse.survey([tmp_path])}

    assert notes == {"server.log": "empty", "server.log.1": "no timestamps"}


def test_the_command_prints_a_table_with_readable_sizes(rotation):
    result = runner.invoke(main.app, ["list", str(rotation)])

    assert result.exit_code == 0
    assert "server.log.2026-09-25" in result.stdout
    assert "2026-09-25 23:59:59" in result.stdout
    assert "server.log_rotating_lock" not in result.stdout


def test_json_carries_sizes_in_bytes(rotation):
    result = runner.invoke(main.app, ["--output-format", "json", "list", str(rotation)])

    rows = json.loads(result.stdout)

    assert [row["path"].rsplit("/", 1)[-1] for row in rows] == [
        "server.log.2026-09-24.gz",
        "server.log.2026-09-25",
        "server.log",
    ]
    assert all(isinstance(row["size"], int) for row in rows)


def test_the_command_takes_a_window(rotation):
    result = runner.invoke(
        main.app,
        ["--output-format", "csv", "--from", "2026-09-25 19:50", "--to", "2026-09-25 20:10", "list", str(rotation)],
    )

    assert result.stdout.count("server.log") == 1
    assert "server.log.2026-09-25" in result.stdout


def test_nothing_to_list_says_so(tmp_path):
    result = runner.invoke(main.app, ["list", str(tmp_path)])

    assert result.exit_code == 0
    assert "(no log files)" in result.stdout


def test_an_archive_is_inflated_once(rotation, monkeypatch):
    first = parse.survey([rotation])

    opened = []
    monkeypatch.setattr(parse.gzip, "open", lambda *args, **kw: opened.append(args))

    assert parse.survey([rotation]) == first
    assert not opened  # a cache miss would have gone through gzip.open


def test_a_rewritten_archive_is_read_again(tmp_path):
    packed = tmp_path / "server.log.1.gz"
    with gzip.open(packed, "wt") as fh:
        fh.write(entries("2026-09-24", "07:00:00", "08:00:00"))
    assert parse.survey([packed])[0]["end"] == datetime(2026, 9, 24, 8, 0, 0, 123000)

    with gzip.open(packed, "wt") as fh:
        fh.write(entries("2026-09-24", "07:00:00", "23:00:00") * 3)

    assert parse.survey([packed])[0]["end"] == datetime(2026, 9, 24, 23, 0, 0, 123000)


def test_a_broken_cache_is_ignored(rotation, cache_home):
    (cache_home / "odoo-logs").mkdir()
    (cache_home / "odoo-logs" / "periods.json").write_text("{not json")

    assert len(parse.survey([rotation])) == 3


def test_entries_for_vanished_files_are_dropped(tmp_path, cache_home):
    packed = tmp_path / "server.log.1.gz"
    with gzip.open(packed, "wt") as fh:
        fh.write(entries("2026-09-24", "07:00:00", "08:00:00"))
    parse.survey([packed])
    packed.unlink()
    (tmp_path / "server.log.2.gz").write_bytes(gzip.compress(entries("2026-09-23", "07:00:00", "08:00:00").encode()))

    parse.survey([tmp_path])

    assert list(json.loads((cache_home / "odoo-logs" / "periods.json").read_text())) == [
        f"{tmp_path / 'server.log.2.gz'}|{(tmp_path / 'server.log.2.gz').stat().st_size}|"
        f"{(tmp_path / 'server.log.2.gz').stat().st_mtime_ns}"
    ]


def test_no_window_prints_nothing_on_stderr(rotation):
    result = runner.invoke(main.app, ["list", str(rotation)])

    assert result.stderr == ""


def test_a_window_is_echoed_on_stderr(rotation):
    result = runner.invoke(main.app, ["--from", "2026-09-25", "list", str(rotation)])

    assert result.stderr == "Getting logs from 2026-09-25 00:00:00 to None\n"
