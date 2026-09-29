# Provenance

The minimal native runtime sources in this directory were vendored from:

```text
https://github.com/zeroknowledgediscovery/lsm
branch/reference: dev-static
source lineage checked against commit:
2c07b57665a443ca05f5e4bf5d86f49943c60ba2
```

Vendored components:

- SourceMapStore
- PredictDistribution
- qdistance
- binary Tree reader
- corresponding headers

DTAG adds `bindings/dtag_lsm_runtime.cpp`, a persistent pybind11 session
wrapper that owns a single source-map store and predictor/tree cache for the
lifetime of a DTAG model session.

The original LSM license is included as `LICENSE`.
