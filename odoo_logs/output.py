from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.table import Table

FORMATS = ("text", "json", "csv")


def _open(output_file: str | None):
    if output_file is None:
        return sys.stdout, False
    return open(output_file, "w"), True


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    return str(value)


class Writer:
    def __init__(self, output_file: str | None, fmt: str):
        self.fmt = fmt
        self._f, self._owned = _open(output_file)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._owned:
            self._f.close()

    def _write(self, text: str):
        print(text, file=self._f)

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        empty_msg: str = "(no results)",
        no_wrap: set[str] | None = None,
    ):
        if not rows:
            self._write(empty_msg)
            return
        t = Table(show_header=True, header_style="bold cyan")
        for h in headers:
            t.add_column(h, overflow="fold", no_wrap=h in (no_wrap or ()))
        for row in rows:
            t.add_row(*row)
        Console(file=self._f).print(t)

    def json(self, data: Any):
        self._write(json.dumps(data, indent=2, default=str))

    def text(self, msg: str):
        self._write(msg)

    def rows(
        self,
        cols: list[str],
        data: list[dict[str, Any]],
        no_wrap: set[str] | None = None,
        empty_msg: str = "(no results)",
    ):
        """One shape in, every format out — so a new one can't miss a command."""
        if self.fmt == "json":
            self.json([{c: row.get(c) for c in cols} for row in data])
            return

        cells = [[_cell(row.get(c)) for c in cols] for row in data]

        if self.fmt == "csv":
            writer = csv.writer(self._f)
            writer.writerow(cols)
            writer.writerows(cells)
            return

        self.table(cols, cells, empty_msg, no_wrap)

    def footer(self, msg: str):
        """A count line under a table; it would be a bogus row in csv/json."""
        if self.fmt == "text":
            self._write(msg)
