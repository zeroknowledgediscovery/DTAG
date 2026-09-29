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

## Binary linkage

On GNU/Linux the build uses:

```text
-static-libstdc++
-static-libgcc
```

and DTAG uses its own `std::thread` worker loop rather than OpenMP. Therefore
the resulting extension should have no dynamic dependency on:

```text
libstdc++.so
libgcc_s.so
libgomp.so
```

`scripts/build_native_bindings.sh` checks this automatically with `ldd` and
fails the build if one of those dependencies remains.

The intended prebuilt binary in this repository is therefore approximately
self-contained except for the host operating-system and Python ABI. A filename
such as:

```text
dtag_lsm.cpython-313-x86_64-linux-gnu.so
```

is specific to CPython 3.13 on x86-64 Linux. Other Python versions,
architectures, or operating systems should rebuild from the bundled source.

## Build dependencies

- C++17 compiler
- CMake >= 3.18
- Git/network access on first build for pybind11 and nlohmann/json

The runtime itself has no dependency on the external LSM repository after it is
built.
