# Archive (deprecated, not maintained)

These files were moved here when the repository was narrowed to two supported products:
the **web app** (`webapp/`, `dtag-web`) and the **optimizer** (`optimizer/` and the
experiments in `scratch/gss2018_pole_geometry/`). The model/map/pole toolchain in `scripts/`
was kept.

Everything here is kept for reference only. It is **not tested, not maintained, and not
runnable in place**. The scripts locate their dependencies relative to `scripts/` and the
repository root, so they only work after being moved back.

| Archived file | Original path | What it was |
|---|---|---|
| `scripts/pipeline.py` | `scripts/pipeline.py` | command-line respondent runtime (`main()`); its library half is `scripts/dtag_core.py` |
| `scripts/interactive.py` | `scripts/interactive.py` | config-driven CLI launcher (`dtag --profile ...`); its profile resolver is now `scripts/dtag_config.py` |
| `scripts/run.py`, `scripts/run_grid.py` | `scripts/` | batch experiment runner and persona/question/order/replicate grid |
| `scripts/post.py`, `scripts/postprocess.py` | `scripts/` | batch postprocessing |
| `scripts/smoke_test.py` | `scripts/` | OpenAI API smoke test |
| `scripts/benchmark_native_runtime.py` | `scripts/` | native runtime benchmark |
| `scripts/eurobarometer_native_cli.py` | `scripts/eurobarometer_native.py` (CLI part) | `--za/--date ... --question` launcher; the library part remains in `scripts/eurobarometer_native.py` |
| `bin/*.sh` | `bin/` | shell launchers for the above (`dtag_demo.sh`, `interactive_config.sh`, `run_config.sh`, `post_config.sh`, `list_experiments.sh`, `run_smoketest.sh`, `smoke_country_pair.sh`) |
| `experiments/question_sequence_optimization/` | `experiments/` | outputs of the earlier question-set optimizer |

Also removed with the CLI:
- the `dtag` console command (`dtag.cli:main`); `dtag-web`, `dtag-models` and `dtag-doctor` remain;
- the CLI test `test_cli_still_runs_through_shared_session` in `webapp/tests/test_native_integration.py`;
- the `--run-openai` option of `scripts/test_native_lsm_dtag.py`.

The `defaults.pipeline/run_grid/postprocess_script` and `experiments:` entries in
`configs/dtag_config.yaml` were read only by the archived runners; they are left in place.

## Restoring a file

```bash
git mv archive/scripts/run.py scripts/run.py
```

The runners also need `scripts/pipeline.py` and `scripts/interactive.py` restored, and the
`dtag` entry point re-added in `setup.py` / `dtag/cli.py`. The commit that archived these files
is the last one in which they were working; the commit before it has the original tree.
