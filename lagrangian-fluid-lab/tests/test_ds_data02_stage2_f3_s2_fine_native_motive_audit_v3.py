from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f3_s2_fine_native_motive_audit_v3.py"
spec = importlib.util.spec_from_file_location("f3_s2_fine_native_motive_v3", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path, role: str) -> dict[str, object]:
    stat = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": _sha(path),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    small = {}
    for role, name, content in (
        ("source", "source.json", b"source metadata\n"),
        ("adapter", "receipt-adapter.json", b"{\"status\":\"completed\"}\n"),
        ("external", "external-v5.json", b"{\"status\":\"COMPLETED_DEVELOPMENT_UNKNOWN\"}\n"),
        ("proof", "proof.json", b"{\"status\":\"verified\"}\n"),
        ("runparts", "RunPARTs.csv", b"Part,TimeStep [s],NpOut,NpOutPos,NpOutRho,NpOutMov\n0,0,0,0,0,0\n"),
        ("run_out", "Run.out", b"Particles of simulation (initial): 1\n"),
        ("xml", "generated.xml", b"<case/>\n"),
        ("pending", "pending.json", b"{\"status\":\"WAITING_FOR_ROOT170_TERMINAL_BINDING\"}\n"),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        small[role] = path
    raw = tmp_path / "solver_output" / "data" / "PartOut_000.obi4"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"native payload that the parent must not open")
    small["raw"] = raw
    refs = {
        "terminal_receipt": _ref(small["adapter"], "terminal_receipt"),
        "external_v5_receipt": _ref(small["external"], "external_v5_receipt"),
        "terminal_proof": _ref(small["proof"], "terminal_proof"),
        "raw_partout": {**_ref(raw, "raw_partout"), "sha256": MODULE.PARENT_GUARD_COMPUTED, "content_opened_by_binder": False},
        "runparts": _ref(small["runparts"], "runparts"),
        "run_out": _ref(small["run_out"], "run_out"),
        "generated_xml": _ref(small["xml"], "generated_xml"),
    }
    pending_ref = _ref(small["pending"], "pending_manifest")
    manifest = {
        "schema": "ds02.stage2.f3.s2.fine-native-motive.manifest.v1",
        "status": "READY_FOR_GUARDED_AUDIT",
        "case": {"case_id": "F3_S2_MATCHED_FINE_SAME_CFL_ROOT_170", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"},
        "source_refs": [_ref(small["source"], "source_metadata")],
        "binder": {"pending_manifest": pending_ref},
        "terminal_binding": {"status": "READY_FOR_GUARDED_AUDIT", "solver_output_root": str((tmp_path / "solver_output").resolve()), "refs": refs},
    }
    final_manifest = tmp_path / "final-manifest.json"
    final_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    runtimes = {}
    for role in ("runtime_v8", "runtime_v6", "runtime_v2", "dispatch_v8", "strict_v8"):
        path = tmp_path / f"{role}.py"
        path.write_text(f"# {role} fixture\n", encoding="utf-8")
        runtimes[role] = path
    return final_manifest, raw, runtimes


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> tuple[dict, Path, Path, dict[str, Path]]:
    final_manifest, raw, runtimes = _fixture(tmp_path)
    output = tmp_path / "parent-request.json"
    kwargs = dict(
        final_manifest=final_manifest,
        output_request=output,
        runtime_v8=runtimes["runtime_v8"],
        runtime_v6=runtimes["runtime_v6"],
        runtime_v2=runtimes["runtime_v2"],
        dispatch_v8=runtimes["dispatch_v8"],
        strict_v8=runtimes["strict_v8"],
        interpreter=Path(sys.executable),
        cwd=SCRIPT.parent,
        worktree_root=SCRIPT.parents[2],
    )
    result = MODULE.build_parent_request(**kwargs)
    return result, output, raw, runtimes


def test_build_parent_request_is_light_validated_and_excludes_raw_payload(tmp_path: Path) -> None:
    result, output, raw, runtimes = _build(tmp_path)
    request = result["request"]
    assert result["light_validation"]["status"] == "LIGHT_VALIDATED_PARENT_V8_NO_RAW_CONTENT"
    assert str(raw.resolve()) not in request["input_files"]
    assert str(raw.resolve()) not in request["input_sha256"]
    assert request["guarded_payload_binding"]["sha256"] == MODULE.PARENT_GUARD_COMPUTED
    assert request["runtime6_closure"]["schema"] == MODULE.RUNTIME6_CLOSURE_SCHEMA
    assert request["cwd"] == str(SCRIPT.parent.resolve())
    assert request["worktree_root"] == str(SCRIPT.parents[2].resolve())
    assert output.is_file()
    assert all(str(path.resolve()) in request["input_files"] for path in runtimes.values())


def test_builder_never_hashes_raw_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = MODULE.sha256_file

    def guarded(path: Path) -> str:
        assert Path(path).name != MODULE.RAW_NAME
        return original(path)

    monkeypatch.setattr(MODULE, "sha256_file", guarded)
    _build(tmp_path)


def test_light_validator_rejects_deferred_raw_parent_hash(tmp_path: Path) -> None:
    result, _, raw, _ = _build(tmp_path)
    request = json.loads(json.dumps(result["request"]))
    request["input_files"].append(str(raw.resolve()))
    request["input_sha256"][str(raw.resolve())] = MODULE.PARENT_GUARD_COMPUTED
    with pytest.raises(MODULE.ParentRequestError, match="raw PartOut"):
        MODULE.light_validate(request)


def test_light_validator_rejects_missing_runtime6_closure(tmp_path: Path) -> None:
    result, _, _, _ = _build(tmp_path)
    request = json.loads(json.dumps(result["request"]))
    del request["runtime6_closure"]
    with pytest.raises(MODULE.ParentRequestError, match="runtime6_closure"):
        MODULE.light_validate(request)


def test_light_validator_rejects_missing_cwd_or_worktree(tmp_path: Path) -> None:
    result, _, _, _ = _build(tmp_path)
    for field in ("cwd", "worktree_root"):
        request = json.loads(json.dumps(result["request"]))
        del request[field]
        with pytest.raises(MODULE.ParentRequestError, match=field):
            MODULE.light_validate(request)
