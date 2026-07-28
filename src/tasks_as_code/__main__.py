"""Allow ``python -m tasks_as_code`` in addition to the ``tasc`` script."""

from __future__ import annotations

from .cli import app

if __name__ == "__main__":
    app()
