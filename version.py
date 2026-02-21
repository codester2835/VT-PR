"""
Module to provide project version.
Reads version from pyproject.toml so it stays in sync.
"""

from pathlib import Path
import toml

def _load_version() -> str:
    """
    Read the version from pyproject.toml.
    """
    base = Path(__file__).parent
    toml_file = base.joinpath("pyproject.toml")
    data = toml.load(toml_file)
    return data["tool"]["poetry"]["version"]

__version__ = _load_version()
