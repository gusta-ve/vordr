"""A tiny stand-in for typer.testing.CliRunner over vordr's argparse ``main()``.

Runs the CLI in-process, feeds ``input`` as stdin and captures stdout+stderr into a
single ``.stdout`` (matching typer's default mixed-stream behaviour) with an ``.exit_code``.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass


@dataclass
class Result:
    exit_code: int
    stdout: str


class CliRunner:
    def invoke(self, app, args, input=None) -> Result:
        buf = io.StringIO()
        old_stdin = sys.stdin
        if input is not None:
            sys.stdin = io.StringIO(input)
        code = 0
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                try:
                    code = app(list(args)) or 0
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        finally:
            sys.stdin = old_stdin
        return Result(code, buf.getvalue())
