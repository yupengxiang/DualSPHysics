#!/usr/bin/env python3
"""Run the adapter's JSON-only identity regression."""
from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parents[1]/'workers/identity_bound_bed_audit_fresh159.py'
spec=importlib.util.spec_from_file_location('fresh159_adapter',p); m=importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(m)
m._toy_check()
