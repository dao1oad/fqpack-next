"""Materialize the frozen 2024-2026 candidate table exactly once."""

from __future__ import annotations

import os
import runpy

os.environ["CLX_START_YEAR"] = "2024"
os.environ["CLX_END_YEAR"] = "2026"
os.environ["CLX_CANDIDATE_OUTPUT"] = (
    "/tmp/clx_trigger_filter_holdout_candidates.parquet"
)
os.environ["CLX_CANDIDATE_SUMMARY"] = (
    "/tmp/clx_trigger_filter_holdout_candidates.summary.json"
)
runpy.run_path("/tmp/build_trigger_filter_candidates.py", run_name="__main__")
