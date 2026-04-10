"""Layered ``.env`` loading shared by the CLI and HTTP clients.

Order:
    1. Current working directory (no override of existing process env).
    2. Repository/package root ``.env`` beside ``avos_cli`` (override) so a
       project-level token wins over cwd.
    3. ``~/.avos/.env`` if present (no override of keys already set).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_layers_loaded = False


def repository_root_env_path() -> Path:
    """Return the path to the ``.env`` file next to the ``avos_cli`` package tree.

    For editable installs this is the project root; for site-packages installs
    it is the directory above the installed ``avos_cli`` package.

    Returns:
        Absolute path whose basename is always ``.env``.
    """
    pkg_root = Path(__file__).resolve().parent.parent.parent
    return pkg_root / ".env"


def load_layers() -> None:
    """Load layered dotenv files once per process."""
    global _layers_loaded
    if _layers_loaded:
        return

    load_dotenv()
    try:
        root_env = repository_root_env_path()
        if root_env.exists():
            load_dotenv(root_env, override=True)
    except OSError:
        pass

    avos_user_env = Path.home() / ".avos" / ".env"
    if avos_user_env.exists():
        load_dotenv(avos_user_env, override=False)

    _layers_loaded = True
