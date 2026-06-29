"""Small local task runner for GraphRCA setup and development."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / "venv"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_FILE = REPO_ROOT / ".env"


def main(argv: list[str] | None = None) -> int:
    """Run one local GraphRCA task."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "setup":
            return _cmd_setup(run_ingest=not args.skip_ingest)
        if args.command == "ingest":
            return _cmd_ingest()
        if args.command == "api":
            return _cmd_api()
        if args.command == "ui":
            return _cmd_ui()
        if args.command == "doctor":
            return _cmd_doctor()
        parser.error(f"Unknown command: {args.command}")
    except subprocess.CalledProcessError as exc:
        print(f"FAIL: command exited with status {exc.returncode}")
        return exc.returncode
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the task runner CLI."""
    parser = argparse.ArgumentParser(description="Local setup and dev tasks for GraphRCA")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Create venv, install deps, prepare .env, and ingest data")
    setup.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Prepare the local environment without loading the dataset into Neo4j.",
    )

    subparsers.add_parser("ingest", help="Load the deterministic dataset into Neo4j")
    subparsers.add_parser("api", help="Start the FastAPI backend from the project venv")
    subparsers.add_parser("ui", help="Start the Chainlit UI from the project venv")
    subparsers.add_parser("doctor", help="Check local prerequisites and config files")
    return parser


def _cmd_setup(*, run_ingest: bool) -> int:
    """Prepare the local Python environment and optionally ingest the dataset."""
    _ensure_env_file()
    _ensure_venv()
    _install_dependencies()
    _print_env_reminder()
    if run_ingest:
        _cmd_ingest()
    print("PASS: local GraphRCA setup complete")
    print("Next steps:")
    print("  python3 make.py api")
    print("  python3 make.py ui")
    return 0


def _cmd_ingest() -> int:
    """Load the benchmark dataset into Neo4j using the project venv."""
    _require_venv()
    _require_env_file()
    _run([str(_venv_python()), "-m", "ingestion.cli", "load-all", "--dataset-path", "data"])
    return 0


def _cmd_api() -> int:
    """Start the FastAPI backend using the project venv."""
    _require_venv()
    _require_env_file()
    _run([str(_venv_python()), "-m", "uvicorn", "api.app:app", "--reload", "--port", "8000"])
    return 0


def _cmd_ui() -> int:
    """Start the Chainlit UI using the project venv."""
    _require_venv()
    _require_env_file()
    _run([str(_venv_bin("chainlit")), "run", "ui/app.py", "-w", "--port", "8001"])
    return 0


def _cmd_doctor() -> int:
    """Report local setup status without mutating anything."""
    print(f"Repo root: {REPO_ROOT}")
    print(f".env.example: {'ok' if ENV_EXAMPLE.exists() else 'missing'}")
    print(f".env: {'ok' if ENV_FILE.exists() else 'missing'}")
    print(f"venv: {'ok' if VENV_DIR.exists() else 'missing'}")
    print(f"python3: {_which('python3') or 'missing'}")
    print(f"neo4j env configured: {'yes' if ENV_FILE.exists() and 'NEO4J_PASSWORD' in ENV_FILE.read_text() else 'unknown'}")
    return 0


def _ensure_env_file() -> None:
    """Create `.env` from `.env.example` when it does not exist."""
    if ENV_FILE.exists():
        return
    if not ENV_EXAMPLE.exists():
        raise FileNotFoundError("Missing .env.example")
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    print("PASS: created .env from .env.example")


def _ensure_venv() -> None:
    """Create the local venv if it does not already exist."""
    if VENV_DIR.exists():
        return
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    print("PASS: created venv")


def _install_dependencies() -> None:
    """Install Python dependencies into the local venv."""
    python = str(_venv_python())
    _run([python, "-m", "pip", "install", "--upgrade", "pip"])
    _run([python, "-m", "pip", "install", "-r", "requirements.txt"])
    print("PASS: installed Python dependencies")


def _print_env_reminder() -> None:
    """Print a small reminder for the local services this repo assumes."""
    print("Reminder:")
    print("  - make sure Neo4j is already running")
    print("  - make sure llama-server is already running")
    print("  - update .env if your Neo4j password or llama endpoint differs from .env.example")


def _require_venv() -> None:
    """Fail fast if the local venv is missing."""
    if not VENV_DIR.exists():
        raise FileNotFoundError("Missing venv. Run `python3 make.py setup` first.")


def _require_env_file() -> None:
    """Fail fast if `.env` is missing."""
    if not ENV_FILE.exists():
        raise FileNotFoundError("Missing .env. Run `python3 make.py setup` first.")


def _venv_python() -> Path:
    """Return the Python executable inside the local venv."""
    return _venv_bin("python")


def _venv_bin(name: str) -> Path:
    """Return one executable path inside the local venv."""
    return VENV_DIR / "bin" / name


def _run(command: list[str]) -> None:
    """Run one command from the repo root and stream output."""
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=os.environ.copy())


def _which(command: str) -> str | None:
    """Return the resolved executable path for one command."""
    return shutil.which(command)


if __name__ == "__main__":
    raise SystemExit(main())
