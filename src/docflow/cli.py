"""Top-level `docflow` CLI dispatcher.

Wires the subcommands used so far: `docflow manifest build <folder>`,
`docflow profile <folder>`, `docflow eval run --system S --manifest M`.
"""

from __future__ import annotations

import sys

from docflow.evals import manifest as manifest_tool
from docflow.evals import runner as eval_runner
from docflow.tools import profile as profile_tool
from docflow.tools import synth as synth_tool

_USAGE = (
    "usage: docflow <manifest build <folder> | profile <folder> | "
    "eval run --system S --manifest M | synth generate [--out DIR] [--labels-out DIR] "
    "[--seed N] [--n N]>"
)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        _usage_error()

    command, rest = args[0], args[1:]

    if command == "manifest":
        if not rest or rest[0] != "build":
            _usage_error()
        manifest_tool.main(rest[1:])
    elif command == "profile":
        profile_tool.main(rest)
    elif command == "eval":
        if not rest or rest[0] != "run":
            _usage_error()
        eval_runner.main(rest[1:])
    elif command == "synth":
        if not rest or rest[0] != "generate":
            _usage_error()
        synth_tool.main(rest[1:])
    else:
        _usage_error()


def _usage_error() -> None:
    print(_USAGE, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
