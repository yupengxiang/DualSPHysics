from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_root_review_v4 import (
    CASE_ID,
    OUTPUT,
    OUTPUT_PREFIX,
    verify,
)


def test_v4_root_review_authorizes_only_one_cpu_native_preflight():
    receipt = verify(OUTPUT)
    assert receipt["authorized_case_id"] == CASE_ID
    assert receipt["authorized_matrix_index"] == 4
    assert receipt["authorization"]["cpu_gencase"] is True
    assert receipt["authorization"]["native_decode"] is True
    assert receipt["authorization"]["solver_launch"] is False
    assert receipt["authorization"]["gpu_launch"] is False
    assert receipt["matrix_credit"] == 0
    assert receipt["failure_denominator"]["qualification_numerator"] == 0


def test_v4_root_review_keeps_new_output_fresh_and_parent_closed():
    receipt = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert receipt["case"]["output_prefix_unmaterialized"] is True
    assert not OUTPUT_PREFIX.exists()
    # The receipt was issued before the one-shot preflight.  The stem itself
    # remains a non-file, while the immutable post-run evidence directory is
    # now expected to exist.
    assert OUTPUT_PREFIX.parent.is_dir()
    assert (OUTPUT_PREFIX.parent / "preflight.json").is_file()
    assert receipt["hash_review"]["parent_matrix_all_not_started"] is True
    assert receipt["hash_review"]["parent_matrix_rows"] == 15
    assert ".bi4" not in json.dumps(receipt, sort_keys=True).lower()


def test_v4_root_review_records_no_runtime_or_mutation():
    receipt = json.loads(OUTPUT.read_text(encoding="utf-8"))
    controls = receipt["execution_controls"]
    for key in ("cpu_gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        assert controls[key] is False
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        assert controls[key] == 0
