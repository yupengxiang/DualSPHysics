#!/usr/bin/env python3
"""Run the mature F5 typed BI4 converter against the immutable reference-009 runs.

The historical converter has a fixed case table for the older coarse products.
This thin, additive entry point supplies the two reference-009 paths while
delegating every decode, typed-axis, PartVTK, HDF5, and transport operation to
``ds_data02_f5_native.py``.  It never launches a solver and never mutates the
raw solver tree.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
BASE_SCRIPT = LAB_ROOT / "scripts/ds_data02_f5_native.py"

CASE_SPECS = {
    "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009": {
        "mechanism_id": "runup_return",
        "background": "runup_return",
        "case_root": DATA_ROOT / "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "attempt_id": "qualification-f5-runup_return-phase-exact-007-native-reference-009-domain-repair-011",
        "gencase_attempt": "native_inputs_domain_repair_011",
        "solver_attempt": "qualification-f5-runup_return-phase-exact-007-native-reference-009-domain-repair-011",
        "generated_xml_name": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007.xml",
        "motion_name": "piston_f91973457a049db5_regular_piston.dat",
        "metadata": LAB_ROOT / "campaigns/ds-data-02/families/F5/definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "weir": False,
        "weir_x0": None,
        "weir_x1": None,
        "weir_base_z": None,
        "weir_crest_z": None,
    },
    "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009": {
        "mechanism_id": "weir_pair",
        "background": "weir_pair",
        "case_root": DATA_ROOT / "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "attempt_id": "qualification-f5-weir_pair-phase-exact-007-native-reference-009-domain-repair-011",
        "gencase_attempt": "native_inputs_domain_repair_011",
        "solver_attempt": "qualification-f5-weir_pair-phase-exact-007-native-reference-009-domain-repair-011",
        "generated_xml_name": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007.xml",
        "motion_name": "piston_4c73cd98b7230035_regular_piston.dat",
        "metadata": LAB_ROOT / "campaigns/ds-data-02/families/F5/definitions/F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "weir": True,
        "weir_x0": 4.96,
        "weir_x1": 5.20,
        "weir_base_z": 0.3648,
        "weir_crest_z": 0.4748,
    },
}


def _load_base():
    spec = importlib.util.spec_from_file_location("ds_data02_f5_native_mature", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mature converter: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch(module) -> None:
    # The mature implementation only reads these fields during convert/label.
    # Keeping the patch local to this process avoids changing the consumed
    # coarse case table or its historical requests.
    module.CASE_SPECS = CASE_SPECS
    module.SCRIPT = SCRIPT
    module.LAB_ROOT = LAB_ROOT
    module.WORKTREE_ROOT = SCRIPT.parents[2]
    module.EVENT_DEFINITIONS = LAB_ROOT / "campaigns/ds-data-02/families/F5/event_definitions.json"
    module.QUALITY_CONTRACT = LAB_ROOT / "campaigns/ds-data-02/families/F5/quality_contract.json"
    module.CONVERTER = LAB_ROOT / "scripts/ds_data02_f5_bi4.py"
    module.PYTHON = Path(sys.executable)


def main(argv: list[str] | None = None) -> int:
    module = _load_base()
    _patch(module)
    return int(module.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
