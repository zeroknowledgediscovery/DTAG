# Bundled DTAG native LSM runtime

This directory contains the minimal native C++ runtime required by Digital Twin
Anchored Generation (DTAG). It is vendored into DTAG so a fresh clone does not
need a sibling LSM repository.

Build once:

```bash
bash scripts/build_native_bindings.sh
```

The build writes the Python extension to:

```text
native/lsm_runtime/python/dtag_lsm*.so
```

DTAG automatically prefers this bundled extension.

## Session model

`dtag_lsm.Runtime` is persistent for the lifetime of the Python
`NativeLSMBackend` object. At construction it:

1. opens the selected native model;
2. loads/caches source-map dictionaries;
3. preloads all usable binary trees;
4. retains those objects in memory.

Subsequent `predict_distributions`, `qdistance`, and ideology-distance calls
reuse those caches. Switching to another DTAG process/model creates another
runtime object.

Each loaded tree also caches its subtree target masses (used when marginalizing over missing
inputs) and the set of columns it splits on, so these are no longer rebuilt per prediction.

### Incremental evaluation of single-answer extensions

`Runtime.extension_distances(left, right, state, extensions, tree_ids)` returns
`d(L, s)`, `d(R, s)` and, for every `(column, token)` in `extensions`, the distances of
`s + {column = token}`. It is exactly equal to calling `distances_to_state` on each extended
state, but:

- pole predictions `p_t(L)`, `p_t(R)` are cached across calls;
- `p_t(s)` and the per-tree JSDs of the base state are computed once per call;
- for an extension on column `c`, only the trees that split on `c` are re-predicted (a tree's
  inference never reads a column it does not split on); every other tree reuses its base value;
- the per-tree values are reduced in the original tree order, so results are bit-identical.

On GSS 2018 (1,034 trees; a column is split on by ~18 trees at the median) a full one-step
sweep of ~7,150 extensions takes ~4.5 s instead of ~190 s. `Runtime.split_columns(tree_ids)`
exposes the split-column sets.

The clean DTAG branch does not use the old stateless external extension
modules. Build this bundled runtime before running DTAG.

## Binary linkage

DTAG compiles the full LSM inference implementation directly into
`dtag_lsm*.so`: source-map handling, binary-tree loading, prediction,
qdistance, and the persistent session wrapper all live in that one extension.

The extension deliberately uses the host `libstdc++` and `libgcc` dynamically.
Statically embedding those runtimes inside a pybind11 extension can create
duplicate C++ ABI/exception/RTTI state inside the Python process and is not a
safe portability strategy.

DTAG does **not** depend on OpenMP or `libgomp`; tree-level parallelism uses
`std::thread`. The build script verifies that `libgomp` is absent.

A prebuilt filename such as:

```text
dtag_lsm.cpython-313-x86_64-linux-gnu.so
```

is specific to its CPython/platform ABI. Comparable Linux/CPython environments
can use it directly; other environments should rebuild from the bundled source.

## Build dependencies

- C++17 compiler
- CMake >= 3.18
- Git/network access on first build for pybind11 and nlohmann/json

The runtime itself has no dependency on the external LSM repository after it is
built.
