from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from scripts import f8_r008_solver_output_core_input_gate_v1 as gate
from scripts import f8_r008_native_integrity_registry_v1 as native_registry


CASE_ID = native_registry.EXPECTED_QUALIFICATION_CASE_IDS[0]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value) if not isinstance(value, bytes) else value).hexdigest()


def _descriptor() -> dict[str, object]:
    frames = [
        {
            "ordinal": ordinal,
            "path": f"frames/Part_{ordinal:04d}.bi4",
            "bytes": 32 + ordinal,
            "sha256": _sha(f"synthetic-frame-{ordinal}".encode()),
            "time_ieee754_hex": time_hex,
        }
        for ordinal, (time_hex, _unused) in enumerate(
            (("0x0.0p+0", 0), ("0x1.0000000000000p-1", 1),
             ("0x1.0000000000000p+0", 2))
        )
    ]
    raw_manifest = {
        "role": "raw_solver_manifest",
        "path": "manifests/outputs-manifest.json",
        "bytes": 128,
        "sha256": _sha(b"synthetic-raw-solver-manifest"),
    }
    decoded_manifest = {
        "role": "decoded_frame_manifest",
        "path": "manifests/decoded-frame-manifest.json",
        "bytes": 256,
        "sha256": _sha(b"synthetic-decoded-frame-manifest"),
    }
    native_table = {
        "role": "native_fluid_table",
        "path": "outputs/native-fluid-frame-table-v2.h5",
        "bytes": 4096,
        "sha256": _sha(b"synthetic-native-fluid-table"),
    }
    input_bindings = {
        "definition_sha256": _sha(b"synthetic-definition"),
        "control_sha256": _sha(b"synthetic-control"),
        "initial_state_sha256": _sha(b"synthetic-initial-state"),
        "configuration_sha256": _sha(b"synthetic-configuration"),
        "parameter_contract_sha256": _sha(b"synthetic-parameter-contract"),
        "raw_solver_manifest_sha256": raw_manifest["sha256"],
        "decoded_frame_manifest_sha256": decoded_manifest["sha256"],
        "native_table_sha256": native_table["sha256"],
        "case_np": 4,
        "fluid_particle_count": 2,
        "fluid_id_order_sha256": _sha(b"synthetic-fluid-id-order"),
    }
    output = {
        "case_id": CASE_ID,
        "attempt_id": "synthetic-attempt-001",
        "nonce_hex": "0123456789abcdef0123456789abcdef",
        "raw_solver_manifest": raw_manifest,
        "decoded_frame_manifest": decoded_manifest,
        "native_fluid_table": native_table,
        "frames": frames,
        "frame_count": len(frames),
        "case_np": input_bindings["case_np"],
        "fluid_particle_count": input_bindings["fluid_particle_count"],
        "fluid_id_order_sha256": input_bindings["fluid_id_order_sha256"],
        "frame_manifest_sha256": _sha(frames),
        "time_axis_sha256": _sha([frame["time_ieee754_hex"] for frame in frames]),
    }
    return {
        "schema": gate.SCHEMA,
        "scope_id": gate.SCOPE_ID,
        "input_origin": gate.INPUT_ORIGIN,
        "case_id": CASE_ID,
        "split": "qualification",
        "attempt": {
            "attempt_id": "synthetic-attempt-001",
            "nonce_hex": "0123456789abcdef0123456789abcdef",
        },
        "input_bindings": input_bindings,
        "output": output,
        "core_projection": {**gate.EXPECTED_CORE_PROJECTION, "case_id": CASE_ID},
        "authorization": dict(gate.EXPECTED_AUTHORIZATION),
    }


def _raw(value: dict[str, object] | None = None) -> bytes:
    return _canonical(_descriptor() if value is None else value)


def test_valid_descriptor_projects_to_diagnostic_core_input() -> None:
    raw = _raw()
    result = gate.project_solver_output_to_core_input(raw)

    assert result["schema"] == gate.PROJECTION_SCHEMA
    assert result["status"] == gate.STATUS
    assert result["scope_id"] == gate.SCOPE_ID
    assert result["input_descriptor_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["case_id"] == CASE_ID
    assert result["output"]["frame_count"] == 3
    assert result["output"]["frames"][2]["ordinal"] == 2
    assert result["authorization"] == gate.EXPECTED_AUTHORIZATION


def test_case_np_fluid_population_and_digest_bindings_are_not_self_declared() -> None:
    descriptor = _descriptor()
    descriptor["output"] = copy.deepcopy(descriptor["output"])
    descriptor["output"]["case_np"] = 5
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="case_np"):
        gate.project_solver_output_to_core_input(_raw(descriptor))

    descriptor = _descriptor()
    descriptor["output"] = copy.deepcopy(descriptor["output"])
    descriptor["output"]["attempt_id"] = "synthetic-attempt-other"
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="attempt_id"):
        gate.project_solver_output_to_core_input(_raw(descriptor))

    descriptor = _descriptor()
    descriptor["input_bindings"] = copy.deepcopy(descriptor["input_bindings"])
    descriptor["input_bindings"]["fluid_id_order_sha256"] = "0" * 64
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="fluid_id_order_sha256"):
        gate.project_solver_output_to_core_input(_raw(descriptor))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["output"]["frames"][0].update({"path": "../Part_0000.bi4"}), "unsafe path"),
        (lambda value: value["output"]["frames"][1].update({"ordinal": 0}), "contiguous"),
        (lambda value: value["output"]["frames"][1].update({"time_ieee754_hex": "0x0.0p+0"}), "strictly increasing"),
        (lambda value: value["output"].update({"frame_manifest_sha256": "0" * 64}), "frame_manifest_sha256"),
        (lambda value: value["output"]["native_fluid_table"].update({"path": "outputs/../table.h5"}), "unsafe path"),
    ],
)
def test_frame_and_artifact_rebinding_fails_closed(mutation, message: str) -> None:
    descriptor = _descriptor()
    mutation(descriptor)
    with pytest.raises(gate.SolverOutputCoreInputGateError, match=message):
        gate.project_solver_output_to_core_input(_raw(descriptor))


def test_authority_promotion_partial_output_and_unknown_case_are_rejected() -> None:
    descriptor = _descriptor()
    descriptor["authorization"] = copy.deepcopy(descriptor["authorization"])
    descriptor["authorization"]["qualification_credit"] = 1
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="authority"):
        gate.project_solver_output_to_core_input(_raw(descriptor))

    descriptor = _descriptor()
    descriptor["output"] = copy.deepcopy(descriptor["output"])
    descriptor["output"]["frame_count"] = 2
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="frame_count"):
        gate.project_solver_output_to_core_input(_raw(descriptor))

    descriptor = _descriptor()
    descriptor["case_id"] = "not-a-frozen-r008-case"
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="frozen R008"):
        gate.project_solver_output_to_core_input(_raw(descriptor))


def test_canonical_duplicate_key_and_size_boundaries_fail_before_projection() -> None:
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="canonical|duplicate"):
        gate.project_solver_output_to_core_input(b'{"schema":"x","schema":"y"}')

    raw = _raw()
    with pytest.raises(gate.SolverOutputCoreInputGateError, match="canonical"):
        gate.project_solver_output_to_core_input(raw + b"\n")

    with pytest.raises(gate.SolverOutputCoreInputGateError, match="bounded byte limit"):
        gate.project_solver_output_to_core_input(b"{" + b"x" * gate.MAX_JSON_BYTES)


def test_contract_has_no_filesystem_or_execution_surface() -> None:
    source = inspect.getsource(gate)
    tree = ast.parse(source)
    imported_modules = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported_modules.intersection({"os", "h5py", "subprocess", "ctypes"})
    assert "Popen" not in source
    assert "os.system" not in source


def test_report_matches_deterministic_contract_report() -> None:
    report_path = Path(gate.__file__).resolve().parents[1] / "reports" / (
        "F8-R008-SOLVER-OUTPUT-CORE-INPUT-GATE-V1.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == gate.build_report()
