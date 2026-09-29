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

The clean DTAG branch does not use the old stateless external extension
modules. Build this bundled runtime before running DTAG.

## Build dependencies

- C++17 compiler
- CMake >= 3.18
- Git/network access on first build for pybind11 and nlohmann/json

The runtime itself has no dependency on the external LSM repository after it is
built.
