from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path


def runtime_root() -> Path:
    override = os.environ.get("DTAG_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    root = Path(sysconfig.get_path("data")) / "share" / "dtag"
    if not root.is_dir():
        raise SystemExit(
            "Installed DTAG runtime tree was not found at "
            f"{root}. Reinstall DTAG from the repository."
        )
    return root


def _exec(script: str, argv: list[str]) -> int:
    root = runtime_root()
    path = root / "scripts" / script
    if not path.is_file():
        raise SystemExit(f"Installed DTAG script is missing: {path}")

    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    script_dir = str(root / "scripts")
    env["PYTHONPATH"] = (
        script_dir if not existing else script_dir + os.pathsep + existing
    )

    return subprocess.call(
        [sys.executable, str(path), *argv],
        cwd=str(root),
        env=env,
    )


def main() -> None:
    raise SystemExit(
        _exec(
            "interactive.py",
            [
                "--config",
                str(runtime_root() / "configs" / "dtag_config.yaml"),
                *sys.argv[1:],
            ],
        )
    )


def models_main() -> None:
    raise SystemExit(_exec("fetch_models.py", sys.argv[1:]))


def web_main() -> None:
    """Launch the DTAG web application (FastAPI + built browser UI)."""
    root = runtime_root()
    backend = root / "webapp" / "backend"
    if not (backend / "dtag_web" / "app.py").is_file():
        raise SystemExit(f"Installed DTAG web application is missing: {backend}")
    env = dict(os.environ)
    paths = [str(backend), str(root / "scripts")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("DTAG_RUNTIME_ROOT", str(root))
    raise SystemExit(
        subprocess.call([sys.executable, "-m", "dtag_web", *sys.argv[1:]], cwd=str(root), env=env)
    )


def doctor_main() -> None:
    root = runtime_root()
    scripts = [
        ["check_dtag_readiness.py"],
        ["audit_clean_repo.py", "--allow-local-legacy"],
    ]
    rc = 0
    for args in scripts:
        rc = _exec(args[0], args[1:])
        if rc:
            break
    raise SystemExit(rc)
