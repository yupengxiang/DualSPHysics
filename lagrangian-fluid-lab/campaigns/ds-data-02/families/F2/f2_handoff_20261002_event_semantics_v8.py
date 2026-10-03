#!/usr/bin/env python3
"""DS-DATA-02 Family F2: Event Semantics v8 Handoff Module.

Alias pointing to f2_rv4eq_fine_dense_full4001_event_semantics_v8.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parent / "f2_rv4eq_fine_dense_full4001_event_semantics_v8.py"
if str(_TARGET.parent) not in sys.path:
    sys.path.insert(0, str(_TARGET.parent))

from f2_rv4eq_fine_dense_full4001_event_semantics_v8 import *
from f2_rv4eq_fine_dense_full4001_event_semantics_v8 import (
    observe,
    operator_spec,
    operator_hash,
    main,
    apply_monkeypatch,
    _native_mass_reference_v8,
    SCHEMA,
    OPERATOR_VERSION,
    FROZEN_V6_OPERATOR_VERSION,
    V6_CODE_SHA256,
    NATIVE_FLOAT32_MASSFLUID_KG,
    FINE_FLUID_PARTICLE_COUNT,
    NATIVE_FLOAT32_COHORT_MASS_KG,
    XML_DECIMAL_MASSFLUID_KG,
    XML_DECIMAL_COHORT_MASS_KG,
    REPRESENTATION_DELTA_KG,
    REPRESENTATION_RELATIVE_DELTA,
)

if __name__ == "__main__":
    raise SystemExit(main())
