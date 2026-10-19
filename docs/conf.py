"""Sphinx configuration for ruim2rxnorm.

Build with::

    uv sync --group docs
    uv run ruim2rxnorm-docs   # sphinx-build -W -b html docs docs/_build/html
"""

from __future__ import annotations

import os
import sys
from datetime import date

# Make the package importable for autodoc when not installed.
sys.path.insert(0, os.path.abspath(".."))

try:
    from ruim2rxnorm import __version__ as _version
except Exception:  # pragma: no cover - docs build without an install
    _version = "0.1.0"

# -- Project information ------------------------------------------------------

project = "ruim2rxnorm"
author = "ruim2rxnorm contributors"
copyright = f"{date.today().year}, {author}"
version = _version
release = _version

# -- General configuration ----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
root_doc = "index"

# -- Autodoc ------------------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

# -- HTML output --------------------------------------------------------------

html_theme = "alabaster"
html_static_path = ["_static"]
html_title = f"ruim2rxnorm {release}"
