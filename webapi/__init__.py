from __future__ import annotations


def create_app():
    from .main import create_app as _create_app

    return _create_app()


try:
    from .main import app
except Exception:  # pragma: no cover - allows lightweight imports before optional deps
    app = None


__all__ = ["app", "create_app"]
