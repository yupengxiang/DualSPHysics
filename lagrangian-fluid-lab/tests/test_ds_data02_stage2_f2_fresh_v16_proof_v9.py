from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v9.py"
spec = importlib.util.spec_from_file_location("proof_v9_under_test", SCRIPT)
assert spec is not None and spec.loader is not None
v9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v9)


def test_declared_typed_input_provenance_is_recorded_without_open_allowlist():
    typed = "/var/tmp/ds02-stage2/old-products/typed-reconstructed-v2.h5"
    converter = "/var/tmp/ds02-stage2/old-products/raw-converter-report-v2.json"
    v9._DECLARED_PROVENANCE = {typed, converter}
    value = {"typed_input_binding": {"path": typed,
                                     "producer_converter_report": {"path": converter}}}
    observed = v9._path_audit_v9(value, original_roots=[], allowed_roots=[Path("/var/tmp/new")])
    assert observed["provenance_paths"] == sorted([typed, converter])
    assert observed["actionable_original_path_hits"] == []
    assert observed["unbound_absolute_paths"] == []
    v9._DECLARED_PROVENANCE = set()


def test_undeclared_absolute_path_still_fails_closed():
    declared = "/var/tmp/ds02-stage2/old-products/typed-reconstructed-v2.h5"
    unbound = "/var/tmp/ds02-stage2/old-products/other.json"
    v9._DECLARED_PROVENANCE = {declared}
    observed = v9._path_audit_v9({"typed_input_binding": {"path": declared}, "other": unbound},
                                 original_roots=[], allowed_roots=[Path("/var/tmp/new")])
    assert observed["provenance_paths"] == [declared]
    assert observed["unbound_absolute_paths"] == [unbound]
    v9._DECLARED_PROVENANCE = set()


def test_declared_path_must_come_from_small_producer_report():
    report = {
        "schema": v9.PRODUCER_SCHEMA,
        "labels": {"v16": {"path": "/var/tmp/new/result.json"}},
        "typed_input": {
            "path": "/var/tmp/old/typed.h5",
            "pre_stat": {"path": "/var/tmp/old/typed.h5"},
            "post_stat": {"path": "/var/tmp/old/typed.h5"},
        },
        "v37_provenance": {"converter_report": {"path": "/var/tmp/old/converter.json"}},
    }
    assert v9._derive_producer_paths(report) == {"/var/tmp/old/typed.h5", "/var/tmp/old/converter.json"}
