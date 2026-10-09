"""ROOT191 V5 metadata-only tests using the real ROOT200 result stat."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root191_v5_stat_enriched_builder.py"
RUNNER = ROOT / "scripts/ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v5.py"
RESULT = Path(
    "/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "products/v16-reconstructed-label-result-v2.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("root191_v5_stat_builder_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runner():
    spec = importlib.util.spec_from_file_location("root191_v5_runner_test", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready():
    return RESULT.is_file()


@pytest.mark.skipif(not _ready(), reason="ROOT200 deferred result is not mounted")
def test_real_root200_stat_only_build_and_admission(tmp_path: Path):
    builder = _load()
    output = tmp_path / "root191-v5-stat-enriched.json"
    value = builder.build_enriched(
        output=output,
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V3_V5_STAT_ENRICHED",
        case_id="f2-s1-root191-v5-stat-enriched-test",
        attempt_id="f2-s1-root191-v5-stat-enriched-test-root-forward-030-001",
    )
    assert value["payload_read"] is False
    checked = builder.validate_enriched(output)
    assert checked["status"] == "ROOT191_V5_FULL_STAT_METADATA_VALIDATED"
    request = builder._json(output, "request")
    stat = request["root191_v5_stat_contract"]["current_full_stat"]
    assert set(stat) == set(builder.FULL_STAT_FIELDS)
    assert all(isinstance(stat[field], int) for field in builder.FULL_STAT_FIELDS)
    assert request["root200_binding"]["result"]["stat"] == stat
    proof = request["root191_v5_stat_contract"]["root200_actual_proof"]
    assert proof["proof_source_result_stat_is_partial"] is True
    assert proof["missing_from_root200_proof"] == ["ctime_ns", "st_dev", "st_ino"]
    # The builder only stat'ed the 62 MB result; it must not claim to have
    # consumed its JSON content.
    assert request["root191_v5_stat_enriched_builder"]["metadata_read_pass"]["result_content_read"] is False


@pytest.mark.skipif(not _ready(), reason="ROOT200 deferred result is not mounted")
def test_v5_rejects_any_full_stat_drift_without_touching_result(tmp_path: Path):
    builder = _load()
    output = tmp_path / "root191-v5-stat-enriched.json"
    builder.build_enriched(
        output=output,
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V3_V5_STAT_ENRICHED",
        case_id="f2-s1-root191-v5-stat-enriched-negative",
        attempt_id="f2-s1-root191-v5-stat-enriched-negative-root-forward-030-001",
    )
    request = builder._json(output, "request")
    request["root191_v5_stat_contract"]["result"]["expected_pre_stat"]["st_ino"] += 1
    request["sha256"] = builder._canonical(request)
    bad = tmp_path / "root191-v5-stat-enriched-bad.json"
    bad.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(builder.Root191V5BuilderError, match="expected pre/post stat"):
        builder.validate_enriched(bad)


@pytest.mark.skipif(not _ready(), reason="ROOT200 deferred result is not mounted")
def test_v5_runtime_admission_uses_all_full_stat_fields(tmp_path: Path):
    builder = _load()
    runner = _load_runner()
    output = tmp_path / "root191-v5-runtime-admission.json"
    builder.build_enriched(
        output=output,
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V3_V5_RUNTIME_ADMISSION",
        case_id="f2-s1-root191-v5-runtime-admission",
        attempt_id="f2-s1-root191-v5-runtime-admission-root-forward-030-001",
    )
    checked = runner.validate_request(output)
    assert checked["status"] == "ROOT191_V5_FULL_STAT_VALIDATED_READY_FOR_PARENT"
    request = builder._json(output, "request")
    request["root200_binding"]["result"]["stat"]["st_dev"] += 1
    request["sha256"] = builder._canonical(request)
    bad = tmp_path / "root191-v5-runtime-admission-bad.json"
    bad.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises((runner.Root191V5Error, runner.BUILDER.Root191V5BuilderError), match="stat"):
        runner.validate_request(bad)
