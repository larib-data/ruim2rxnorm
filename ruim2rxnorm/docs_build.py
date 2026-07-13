"""Console entry point ``ruim2rxnorm-docs`` — (re)build the Sphinx HTML docs.

A thin wrapper around ``sphinx-build -W -b html docs docs/_build/html`` so the
documentation can be rebuilt with a single command::

    uv run ruim2rxnorm-docs                 # build docs/_build/html (warnings = errors)
    uv run ruim2rxnorm-docs -- -a -E        # extra args are forwarded to sphinx-build

Sphinx is an opt-in dependency (the ``docs`` group), not a runtime requirement;
install it first with ``uv sync --group docs``.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional


def _docs_dir() -> str:
    """Locate the ``docs`` source directory (repo layout, else CWD)."""
    # This module lives at <repo>/ruim2rxnorm/docs_build.py, so the docs tree is
    # a sibling of the package directory.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(repo_root, "docs")
    if os.path.isdir(candidate):
        return candidate
    # Fall back to the current working directory (e.g. a non-editable install).
    return os.path.join(os.getcwd(), "docs")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        from sphinx.cmd.build import main as sphinx_main
    except ModuleNotFoundError:
        print(
            "ruim2rxnorm-docs: Sphinx is not installed. "
            "Run 'uv sync --group docs' first.",
            file=sys.stderr,
        )
        return 1

    source = _docs_dir()
    if not os.path.isfile(os.path.join(source, "conf.py")):
        print(
            f"ruim2rxnorm-docs: no Sphinx project found at {source!r} "
            "(run from the repository root).",
            file=sys.stderr,
        )
        return 1

    build = os.path.join(source, "_build", "html")
    return sphinx_main(["-W", "-b", "html", source, build, *argv])


if __name__ == "__main__":
    raise SystemExit(main())
