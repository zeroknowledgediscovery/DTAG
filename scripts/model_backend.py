#!/usr/bin/env python3
"""Native LSM runtime interface for DTAG.

This branch is intentionally native-only. A DTAG model is a directory produced
by the C++ LSM trainer and must contain source_maps/ and trees/binary/.

DTAG ships its own persistent native LSM binding under native/lsm_runtime.
Build it once with:

    bash scripts/build_native_bindings.sh

The resulting dtag_lsm extension is loaded directly from the DTAG checkout.
No sibling LSM repository or external inference binding is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np


def _add_lsm_bindings_dir() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundled = repo_root / "native" / "lsm_runtime" / "python"
    if bundled.is_dir() and str(bundled) not in sys.path:
        sys.path.insert(0, str(bundled))


def _native_root(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if (p / "trees" / "binary").is_dir() and (p / "source_maps").is_dir():
        return p
    if p.name == "binary" and p.parent.name == "trees":
        root = p.parent.parent
        if (root / "source_maps").is_dir():
            return root
    raise ValueError(
        f"Not a native LSM model directory: {p}. Expected source_maps/ and trees/binary/."
    )


def detect_backend(path: str | Path) -> str:
    _native_root(path)
    return "native_lsm"

def _discover_tree_ids(root: Path) -> List[int]:
    out: List[int] = []
    for p in (root / "trees" / "binary").glob("tree_*.bin"):
        m = re.fullmatch(r"tree_(\d+)\.bin", p.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(set(out))


def _read_native_columns(root: Path) -> tuple[List[str], Dict[int, List[str]]]:
    """Read column headers and categorical alphabets from native source maps."""
    records: Dict[int, dict] = {}
    shard_dir = root / "source_maps" / "json_shards"
    if not shard_dir.is_dir():
        raise FileNotFoundError(f"Missing native LSM source-map directory: {shard_dir}")

    for path in sorted(shard_dir.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"Could not read source-map shard {path}: {e}") from e

        if not isinstance(obj, dict):
            continue

        # Shards normally contain {"0": {...}, "1": {...}}.  Per-column files
        # are also accepted for compatibility with earlier native snapshots.
        if "column_header" in obj or "column_strings_map" in obj or "to_str" in obj:
            try:
                col = int(path.stem)
            except ValueError:
                continue
            records[col] = obj
            continue

        for key, node in obj.items():
            if not isinstance(node, dict):
                continue
            try:
                col = int(key)
            except Exception:
                continue
            records[col] = node

    if not records:
        raise RuntimeError(f"No column records found in {shard_dir}")

    max_col = max(records)
    names = [""] * (max_col + 1)
    values: Dict[int, List[str]] = {}

    for col, node in records.items():
        name = str(node.get("column_header", "")).strip()
        names[col] = name or f"COL_{col}"

        labels: List[str] = []
        arr = node.get("column_strings_map")
        if isinstance(arr, list):
            for x in arr:
                if x is None:
                    continue
                s = str(x)
                if s != "":
                    labels.append(s)
        elif isinstance(node.get("to_str"), dict):
            pairs = []
            for k, v in node["to_str"].items():
                try:
                    pairs.append((int(k), str(v)))
                except Exception:
                    continue
            for _, s in sorted(pairs):
                if s != "":
                    labels.append(s)
        values[col] = list(dict.fromkeys(labels))

    # A complete native model should have a source-map entry for every original
    # input column.  Fail rather than silently shifting column IDs.
    missing = [i for i, name in enumerate(names) if not name]
    if missing:
        raise RuntimeError(
            f"Native LSM source maps have missing column IDs: {missing[:20]}"
            + (" ..." if len(missing) > 20 else "")
        )
    return names, values


class NativeLSMBackend:
    backend_name = "native_lsm"

    def __init__(
        self,
        path: str | Path,
        cols_per_shard: int = 50000,
        preload: bool = True,
    ):
        _add_lsm_bindings_dir()
        try:
            import dtag_lsm  # type: ignore
        except Exception as e:
            raise ImportError(
                "Bundled DTAG native LSM runtime is not built/importable. "
                "From the DTAG repository run: "
                "bash scripts/build_native_bindings.sh"
            ) from e

        self.root = _native_root(path)
        self.path = str(self.root)
        self.trees_dir = str(self.root / "trees" / "binary")
        self.cols_per_shard = int(cols_per_shard)
        self._runtime_kind = "bundled_persistent"

        self.feature_names, self._values_by_col = _read_native_columns(self.root)
        self._idx = {name: i for i, name in enumerate(self.feature_names)}
        self._tree_ids = _discover_tree_ids(self.root)
        if not self._tree_ids:
            raise RuntimeError(f"No tree_*.bin files found in {self.trees_dir}")

        # Native models can contain structurally present trees whose source-map
        # alphabet is empty (for example, a survey variable that was entirely
        # missing in one wave). Those trees cannot yield a normalized
        # distribution and cause native qdistance to fail with
        # "normalize_counts_to_probs: total count <= 0". Keep the complete tree
        # inventory for diagnostics, but use only supported trees for runtime
        # prediction/distance operations.
        self._usable_tree_ids = [
            tid
            for tid in self._tree_ids
            if tid < len(self.feature_names)
            and bool(self._values_by_col.get(tid, []))
        ]
        if not self._usable_tree_ids:
            raise RuntimeError(
                f"No native LSM trees with categorical support found in {self.trees_dir}"
            )

        self._runtime = dtag_lsm.Runtime(
            self.trees_dir,
            self.path,
            self.cols_per_shard,
            self._usable_tree_ids,
            len(self.feature_names),
            bool(preload),
            bool(preload),
        )

    @property
    def tree_ids(self) -> List[int]:
        return list(self._tree_ids)

    @property
    def usable_tree_ids(self) -> List[int]:
        return list(self._usable_tree_ids)

    def possible_values(self) -> Dict[str, List[str]]:
        return {
            self.feature_names[i]: list(self._values_by_col.get(i, []))
            for i in range(len(self.feature_names))
        }

    def _as_raw_row(self, row: Sequence[str] | np.ndarray) -> np.ndarray:
        vals = ["" if x is None else str(x) for x in list(row)]
        if len(vals) != len(self.feature_names):
            raise ValueError(
                f"State vector has {len(vals)} columns but model has {len(self.feature_names)}"
            )
        return np.asarray(vals, dtype=object)

    def predict_distributions(
        self,
        row: Sequence[str] | np.ndarray,
        target_names: Optional[Sequence[str]] = None,
    ) -> Dict[str, Dict[str, float]]:
        raw = self._as_raw_row(row)
        if target_names:
            usable = set(self._usable_tree_ids)
            tree_ids = [
                self._idx[str(name)]
                for name in target_names
                if str(name) in self._idx and self._idx[str(name)] in usable
            ]
        else:
            tree_ids = self._usable_tree_ids
        if not tree_ids:
            return {}

        result = self._runtime.predict_distributions(raw.tolist(), tree_ids)
        out: Dict[str, Dict[str, float]] = {}
        for tid in tree_ids:
            name = self.feature_names[tid]
            d = result.get(tid, {})
            out[name] = {
                str(k): float(v)
                for k, v in dict(d).items()
                if str(k) != ""
            }
        return out

    def qdistance(self, a: Sequence[str] | np.ndarray, b: Sequence[str] | np.ndarray) -> float:
        aa = ["" if x is None else str(x) for x in list(a)]
        bb = ["" if x is None else str(x) for x in list(b)]

        return float(
            self._runtime.qdistance(
                aa,
                bb,
                self._usable_tree_ids,
            )
        )

    def distances_to_state(
        self,
        left: Sequence[str] | np.ndarray,
        right: Sequence[str] | np.ndarray,
        state: Sequence[str] | np.ndarray,
    ) -> tuple[float, float]:
        ll = ["" if x is None else str(x) for x in list(left)]
        rr = ["" if x is None else str(x) for x in list(right)]
        ss = ["" if x is None else str(x) for x in list(state)]

        d_left, d_right = self._runtime.distances_to_state(
            ll,
            rr,
            ss,
            self._usable_tree_ids,
        )
        return float(d_left), float(d_right)

    @property
    def runtime_kind(self) -> str:
        return self._runtime_kind

    def cache_signature(self) -> str:
        h = hashlib.sha1()
        h.update(str(self.root).encode())
        for rel in ("meta.txt", "manifest.json", "training_manifest.json"):
            p = self.root / rel
            if p.exists():
                st = p.stat()
                h.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}".encode())
        tree_dir = self.root / "trees" / "binary"
        tree_stats = sorted(
            (p.name, p.stat().st_size, p.stat().st_mtime_ns)
            for p in tree_dir.glob("tree_*.bin")
        )
        h.update(repr(tree_stats).encode())
        return f"{self.root}|{h.hexdigest()}|native_lsm"


def load_model(
    path: str | Path,
    backend: str = "auto",
    preload: bool = True,
):
    name = str(backend or "auto").strip().lower()
    if name not in {"auto", "native_lsm", "native", "lsm"}:
        raise ValueError(
            f"DTAG native-only branch does not support backend {backend!r}; "
            "use a native LSM model directory."
        )
    return NativeLSMBackend(path, preload=preload)

def model_feature_names(path: str | Path, backend: str = "auto") -> List[str]:
    return list(load_model(path, backend=backend).feature_names)
