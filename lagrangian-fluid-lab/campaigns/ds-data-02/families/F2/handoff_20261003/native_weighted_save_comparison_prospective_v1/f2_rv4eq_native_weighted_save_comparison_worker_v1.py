#!/usr/bin/env python3
"""DS-DATA-02 Family F2: Native-Weighted Temporal Save Comparison Worker v1 (Handoff Wrapper)."""

from __future__ import annotations

import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parents[2] / "f2_rv4eq_native_weighted_save_comparison_worker_v1.py"
if str(_TARGET.parent) not in sys.path:
    sys.path.insert(0, str(_TARGET.parent))

from f2_rv4eq_native_weighted_save_comparison_worker_v1 import *
from f2_rv4eq_native_weighted_save_comparison_worker_v1 import main

if __name__ == "__main__":
    sys.exit(main())
