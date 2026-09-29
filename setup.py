from __future__ import annotations

from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent

RUNTIME_DIRS = [
    "scripts",
    "configs",
    "maps",
    "assets",
    "bin",
    "native/lsm_runtime",
]

EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "build",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".o",
    ".a",
}


def runtime_data_files():
    groups = {}
    for rel in RUNTIME_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relpath = path.relative_to(ROOT)
            if any(part in EXCLUDE_PARTS for part in relpath.parts):
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            dest = Path("share") / "dtag" / relpath.parent
            groups.setdefault(str(dest), []).append(str(path))

    # Keep top-level metadata next to the installed runtime tree.
    for name in ("README.md", "VERSION", "requirements.txt"):
        p = ROOT / name
        if p.exists():
            groups.setdefault("share/dtag", []).append(str(p))

    return sorted(groups.items())


setup(
    name="dtag",
    version="0.2.0.dev1",
    description="Digital Twin Anchored Generation using native Large Science Models",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://github.com/zeroknowledgediscovery/DTAG",
    packages=find_packages(include=["dtag", "dtag.*"]),
    python_requires=">=3.11",
    install_requires=[
        "openai>=2.0.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "matplotlib>=3.7.0",
        "pyreadstat",
        "pdfplumber",
        "pyyaml>=6.0",
        "zstandard>=0.22.0",
    ],
    data_files=runtime_data_files(),
    entry_points={
        "console_scripts": [
            "dtag=dtag.cli:main",
            "dtag-models=dtag.cli:models_main",
            "dtag-doctor=dtag.cli:doctor_main",
        ]
    },
    include_package_data=True,
)
