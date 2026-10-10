#!/usr/bin/env python3
"""Additive V6 gate for the nine-row native-header source package.

V5's source builder is retained byte-for-byte.  V6 adds the missing terminal
receipt gate and an isolated, real shared-runner fixture.  The gate joins the
exact nine ``(sentinel_id, grid_label)`` rows to their producer request bytes,
runtime receipt, and terminal proof.  It never reads BI4/VTK payloads while
preparing a source package.  A row with a failed receipt, a mismatched hash,
or a duplicate key is rejected; an absent or still-running parent product is
reported as waiting.

The self-test uses the literal project venv and ``ds_data02_runtime_v2``'s
actual ``run_request`` entry through a temporary ledger located inside this
checkout.  It creates tiny producer outputs only.  This is an ABI/contract
fixture and grants no production or scientific credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V5_PATH = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_request_v5.py"
V5 = None
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_SOURCE = HERE.parents[4] / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PROJECT_ROOT = HERE.parents[4]
JSON_CAP = 10 * 1024 * 1024
REQUEST_SCHEMA = "ds02.request.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
EXPECTED_KEYS = {(sid, grid) for sid in TARGETS for grid in GRIDS}
PRODUCT_ROLES = ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4", "gencase_receipt")


class BuildFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load {name}: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v5() -> Any:
    global V5
    if V5 is None:
        V5 = _load(V5_PATH, "stage2_native_header_request_v5_for_v6")
    return V5


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object: {path}")
    return value, _sha_bytes(raw), after


def _small_record(path: Path, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "sha256": _sha_bytes(raw), "bytes": len(raw), "stat": after,
            "stable_read": True, "payload_read_by_v6": False}


def _path_from_record(record: Any, label: str) -> Path | None:
    if record is None:
        return None
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise BuildFailure(f"{label} lacks a path record")
    return _abs(record["path"])


def _declared_record_sha(record: Any, label: str) -> str | None:
    if not isinstance(record, dict):
        raise BuildFailure(f"{label} lacks a record")
    value = record.get("sha256")
    if value is None:
        return None
    if not _valid_sha(value):
        raise BuildFailure(f"{label} has an invalid SHA256")
    return str(value).lower()


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("sentinel_id")), str(row.get("grid_label"))


def _terminal_proof_status(value: Any) -> bool:
    status = str(value or "").upper()
    return bool(status) and "FAIL" not in status and "UNKNOWN" not in status and ("VERIF" in status or "COMPLET" in status)


def validate_source_rows(initial_manifest: Path, product_map: Path) -> dict[str, Any]:
    """Validate rows using only JSON/proof/receipt metadata, never payload bytes.

    ``WAITING`` means a parent product or proof is absent/pending.  ``REJECTED``
    means a concrete identity, SHA, duplicate, or terminal-status violation
    was observed.  ``READY`` requires all nine exact keys and completed rows.
    """
    initial, initial_sha, _ = _small_json(initial_manifest, "initial-support manifest")
    product, product_sha, _ = _small_json(product_map, "nine-row product map")
    expected = set(EXPECTED_KEYS)
    reasons: list[str] = []
    waiting: list[str] = []

    initial_cases = initial.get("cases")
    if not isinstance(initial_cases, list):
        return {"state": "REJECTED", "ready": False, "reasons": ["initial cases is not a list"],
                "initial_sha256": initial_sha, "product_map_sha256": product_sha}
    initial_keys = [_row_key(row) for row in initial_cases if isinstance(row, dict)]
    if len(initial_keys) != len(initial_cases) or len(set(initial_keys)) != len(initial_keys):
        reasons.append("initial manifest has duplicate or malformed row keys")
    if set(initial_keys) != expected:
        missing = sorted(expected - set(initial_keys))
        extra = sorted(set(initial_keys) - expected)
        reasons.append(f"initial key set mismatch missing={missing} extra={extra}")

    rows = product.get("products", product.get("rows"))
    if not isinstance(rows, list):
        return {"state": "REJECTED", "ready": False, "reasons": ["product map has no products list"],
                "initial_sha256": initial_sha, "product_map_sha256": product_sha}
    keys = [_row_key(row) for row in rows if isinstance(row, dict)]
    if len(keys) != len(rows):
        reasons.append("product map has a non-object row")
    if len(set(keys)) != len(keys):
        reasons.append("product map has duplicate row keys")
    if set(keys) != expected:
        missing = sorted(expected - set(keys))
        extra = sorted(set(keys) - expected)
        if missing or extra:
            # A missing parent row is naturally waiting; a foreign row is a
            # concrete source-package error.
            if extra:
                reasons.append(f"product key set has unexpected rows: {extra}")
            if missing:
                waiting.append(f"product rows missing: {missing}")

    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _row_key(row)
        if key not in expected:
            continue
        label = f"{key[0]}:{key[1]}"
        status = str(row.get("status") or product.get("status") or "PENDING")
        status_upper = status.upper()
        if "FAIL" in status_upper:
            reasons.append(f"{label} row status is failure: {status}")
        elif "UNKNOWN" in status_upper:
            reasons.append(f"{label} row status is unknown: {status}")
        elif not ("COMPLET" in status_upper or "VERIF" in status_upper):
            waiting.append(f"{label} row status is pending: {status}")

        producer_record = row.get("producer_request")
        producer_path = _path_from_record(producer_record, f"{label} producer request")
        if producer_path is None or not producer_path.is_file():
            waiting.append(f"{label} producer request is absent")
            continue
        declared_producer_sha = _declared_record_sha(producer_record, f"{label} producer request")
        try:
            producer_doc, producer_sha, _ = _small_json(producer_path, f"{label} producer request")
        except BuildFailure as exc:
            reasons.append(str(exc))
            continue
        if declared_producer_sha and declared_producer_sha != producer_sha.lower():
            reasons.append(f"{label} producer request SHA differs from file")

        products = row.get("products")
        if not isinstance(products, dict):
            waiting.append(f"{label} product role map is absent")
            continue
        missing_roles = [role for role in PRODUCT_ROLES if not isinstance(products.get(role), dict)]
        if missing_roles:
            waiting.append(f"{label} missing product roles: {missing_roles}")
            continue
        for role in PRODUCT_ROLES:
            record = products[role]
            path = _path_from_record(record, f"{label} {role}")
            if path is None or not path.is_file():
                waiting.append(f"{label} {role} is absent")
        receipt_record = products["gencase_receipt"]
        receipt_path = _path_from_record(receipt_record, f"{label} runtime receipt")
        if receipt_path is None or not receipt_path.is_file():
            waiting.append(f"{label} runtime receipt is absent")
        else:
            declared_receipt_sha = _declared_record_sha(receipt_record, f"{label} runtime receipt")
            try:
                receipt, receipt_sha, _ = _small_json(receipt_path, f"{label} runtime receipt")
            except BuildFailure as exc:
                reasons.append(str(exc))
                receipt = {}
                receipt_sha = ""
            if declared_receipt_sha and declared_receipt_sha != receipt_sha.lower():
                reasons.append(f"{label} runtime receipt SHA differs from product map")
            if receipt.get("schema") != "ds02.execution-receipt.v1":
                reasons.append(f"{label} runtime receipt schema is not ds02.execution-receipt.v1")
            receipt_status = str(receipt.get("status") or "")
            try:
                returncode = int(receipt.get("returncode"))
            except (TypeError, ValueError):
                returncode = None
            if receipt_status == "failed" or (returncode is not None and returncode != 0):
                reasons.append(f"{label} runtime receipt failed status={receipt_status!r} returncode={returncode!r}")
            elif receipt_status != "completed" or returncode != 0:
                waiting.append(f"{label} runtime receipt is not terminal completed")
            expected_output = receipt_path.parent.resolve()
            if receipt.get("output_root") != str(expected_output):
                reasons.append(f"{label} receipt output_root does not equal receipt parent")
            if receipt.get("request") != producer_doc:
                reasons.append(f"{label} receipt.request differs from producer request file")
            if receipt.get("request_sha256") != producer_sha:
                reasons.append(f"{label} receipt.request_sha256 does not bind exact producer bytes")
            if producer_doc.get("case_id") != expected_output.parent.name or producer_doc.get("attempt_id") != expected_output.name:
                reasons.append(f"{label} producer case/attempt does not bind output path")
            if producer_doc.get("family_id") != str(row.get("family_id", key[0].split("-", 1)[0])):
                reasons.append(f"{label} producer family does not bind row family")

        proof_record = row.get("actual_proof")
        proof_path = _path_from_record(proof_record, f"{label} terminal proof")
        if proof_path is None or not proof_path.is_file():
            waiting.append(f"{label} terminal proof is absent")
        else:
            declared_proof_sha = _declared_record_sha(proof_record, f"{label} terminal proof")
            try:
                proof, proof_sha, _ = _small_json(proof_path, f"{label} terminal proof")
            except BuildFailure as exc:
                reasons.append(str(exc))
                proof = {}
                proof_sha = ""
            if declared_proof_sha and declared_proof_sha != proof_sha.lower():
                reasons.append(f"{label} terminal proof SHA differs from product map")
            if not _terminal_proof_status(proof.get("status")):
                if "FAIL" in str(proof.get("status") or "").upper():
                    reasons.append(f"{label} terminal proof is failed")
                else:
                    waiting.append(f"{label} terminal proof is not terminal verified")
            if proof.get("row_key") not in (None, f"{key[0]}:{key[1]}"):
                reasons.append(f"{label} terminal proof row_key does not bind row")

    if reasons:
        state = "REJECTED"
    elif waiting:
        state = "WAITING"
    else:
        state = "READY"
    return {"state": state, "ready": state == "READY", "rows": len(rows),
            "expected_rows": len(EXPECTED_KEYS), "exact_key_set": set(keys) == expected and len(keys) == len(set(keys)),
            "reasons": reasons, "waiting": waiting, "initial_sha256": initial_sha,
            "product_map_sha256": product_sha, "scientific_credit": 0,
            "payload_read": False}


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite V6 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build(initial_manifest: Path, product_map: Path, decoder: Path, output_dir: Path,
          initial_request: Path | None = None, admission_manifest: Path | None = None) -> dict[str, Any]:
    """Build V5 only after applying the additive exact terminal-row gate."""
    gate = validate_source_rows(initial_manifest, product_map)
    if gate["state"] == "REJECTED":
        raise BuildFailure("V6 terminal-row gate rejected source package: " + "; ".join(gate["reasons"]))
    result = _v5().build(_abs(initial_manifest), _abs(product_map), _abs(decoder), _abs(output_dir),
                         _abs(initial_request) if initial_request else None,
                         _abs(admission_manifest) if admission_manifest else None)
    final_gate = validate_source_rows(initial_manifest, product_map)
    sidecar = _abs(output_dir) / "native-header-probe-v6-readiness.json"
    _write_once(sidecar, {"schema": "ds02.stage2.three-sentinel-owner-grid-native-header-readiness.v6",
                          "v5_result": result, "terminal_row_gate": final_gate,
                          "payload_read": False, "scientific_credit": 0})
    result = dict(result)
    result["v6_gate"] = final_gate
    if final_gate["state"] == "WAITING":
        result["status"] = "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS_V6"
    elif not final_gate["ready"]:
        result["status"] = "REJECTED_BY_NATIVE_HEADER_V6_TERMINAL_GATE"
    else:
        result["status"] = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V6"
    result["scientific_credit"] = 0
    return result


def _write_runtime_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    producer = root / "tiny_producer.py"
    producer.write_text(
        "from pathlib import Path\nimport sys\n"
        "attempt=Path(sys.argv[1]); case=sys.argv[2]; control=Path('control.csv')\n"
        "if '--fail' in sys.argv: print('intentional tiny producer failure'); raise SystemExit(17)\n"
        "if not control.is_file(): print('relative control.csv missing'); raise SystemExit(19)\n"
        "(attempt/'generated.xml').write_text('<case>'+case+'</case>\\n', encoding='utf-8')\n"
        "(attempt/'generated_Fluid.vtk').write_bytes(b'fluid-tiny\\n')\n"
        "(attempt/'generated_Bound.vtk').write_bytes(b'bound-tiny\\n')\n"
        "(attempt/'generated.bi4').write_bytes(('BI4-'+case).encode())\n"
        "print('tiny producer completed', case)\n", encoding="utf-8")
    control = root / "control.csv"
    control.write_text("time,forcing\n0,0\n", encoding="utf-8")
    launcher = root / "runtime_launcher.py"
    launcher.write_text(
        "import importlib.util,json,sys\nfrom pathlib import Path\n"
        f"src=Path({str(RUNTIME_SOURCE)!r})\n"
        "spec=importlib.util.spec_from_file_location('frozen_runtime_v2_fixture', src)\n"
        "mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "result=mod.run_request(Path(sys.argv[1]), data_root=Path(sys.argv[2]))\n"
        "print(json.dumps(result, sort_keys=True))\n", encoding="utf-8")
    decoder = root / "bi4_dump"
    decoder.write_text(
        "#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\n"
        "prefix=Path(sys.argv[2]); Path(str(prefix)+'.xml').write_text(\n"
        "\"<data><item name='Header'><item name='MassFluid' value='0.5'/><item name='MassBound' value='1.25'/><item name='Dp' value='0.01'/><item name='Nfluid' value='2'/><item name='Nbound' value='1'/></item></data>\", encoding='utf-8')\n",
        encoding="utf-8")
    decoder.chmod(0o755)
    return producer, control, launcher, decoder


def _init_ledger(data_root: Path) -> None:
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    (runtime / "resource-ledger.json").write_text(json.dumps({
        "deadline_utc": deadline.isoformat(),
        "limits": {"gpu_seconds": 0, "cpu_core_seconds": 2000, "new_storage_bytes": 64 * 1024 * 1024,
                    "qualification_attempts": 0, "production_attempts": 0},
        "charges": [], "reservations": [], "attempts": []}, indent=2) + "\n", encoding="utf-8")


def _run_actual_runner(launcher: Path, request: Path, data_root: Path, family: str, case: str, attempt: str) -> dict[str, Any]:
    completed = subprocess.run([str(PYTHON), "-B", str(launcher), str(request), str(data_root)],
                               cwd=str(request.parent), capture_output=True, text=True, timeout=30, check=False)
    receipt_path = data_root / "families" / family / case / attempt / "execution-receipt.json"
    if not receipt_path.is_file():
        raise BuildFailure(f"shared runtime produced no receipt rc={completed.returncode}: {completed.stderr[-1000:]}")
    receipt, _, _ = _small_json(receipt_path, "actual tiny runtime receipt")
    return receipt


def _make_producer_request(path: Path, producer: Path, control: Path, family: str, case: str,
                           attempt: str, cwd: Path, *, fail: bool = False) -> dict[str, Any]:
    command = [str(PYTHON), str(producer), "{attempt_root}", case]
    if fail:
        command.append("--fail")
    request = {
        "schema": REQUEST_SCHEMA, "family_id": family, "case_id": case, "attempt_id": attempt,
        "kind": "cpu", "cpu_task_kind": "audit", "command": command, "cwd": str(cwd),
        "worktree_root": str(PROJECT_ROOT), "max_wall_seconds": 5, "cpu_threads": 1,
        "estimated_storage_bytes": 64 * 1024, "input_files": [str(producer), str(control)],
        "execution_allowed": True, "gencase_launch": False, "solver_launch": False,
        "fixture_only": True, "scientific_credit": 0,
    }
    _write_once(path, request)
    return request


def _fixture_rows(root: Path, launcher: Path, producer: Path, control: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    data_root = root / "tiny-data"
    _init_ledger(data_root)
    initial_rows: list[dict[str, Any]] = []
    product_rows: list[dict[str, Any]] = []
    actual_receipts: dict[str, Any] = {}
    request_dir = root / "producer-requests"
    proof_dir = root / "proofs"
    request_dir.mkdir()
    proof_dir.mkdir()
    for sid in TARGETS:
        for grid in GRIDS:
            key = f"{sid}:{grid}"
            safe = f"{sid.replace('-', '_')}_{grid}"
            family = sid.split("-", 1)[0]
            case = f"tiny_{safe}"
            attempt = f"attempt_{safe}"
            request_path = request_dir / f"{safe}.json"
            request_doc = _make_producer_request(request_path, producer, control, family, case, attempt, root)
            receipt = _run_actual_runner(launcher, request_path, data_root, family, case, attempt)
            if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
                raise BuildFailure(f"actual tiny producer did not complete: {key}: {receipt}")
            output_root = data_root / "families" / family / case / attempt
            names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                     "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                     "gencase_receipt": "execution-receipt.json"}
            products: dict[str, Any] = {}
            for role, name in names.items():
                products[role] = _small_record(output_root / name, f"{key} {role}")
            proof_path = proof_dir / f"{safe}.json"
            proof_doc = {"schema": "ds02.stage2.root-actual-verification.v1",
                         "status": "VERIFIED_ACTUAL_TINY_RUNTIME_FIXTURE", "row_key": key,
                         "producer_request": str(request_path), "producer_request_sha256": _sha_bytes(request_path.read_bytes()),
                         "receipt": str(output_root / "execution-receipt.json"), "scientific_credit": 0}
            proof_path.write_text(json.dumps(proof_doc, sort_keys=True) + "\n", encoding="utf-8")
            initial_rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": family,
                                 "physical_case_id": key})
            product_rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": family,
                                 "physical_case_id": key, "status": "COMPLETED",
                                 "producer_request": {"path": str(request_path), "sha256": _sha_bytes(request_path.read_bytes())},
                                 "products": products,
                                 "actual_proof": _small_record(proof_path, f"{key} proof"),
                                 "control_closure": {"forcing": _small_record(control, f"{key} control")},
                                 "actual_control_cwd": str(root)})
            actual_receipts[key] = {"receipt": receipt, "request": request_doc, "request_path": request_path,
                                    "receipt_path": output_root / "execution-receipt.json"}
    initial_path = root / "initial.json"
    initial_path.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1",
                                        "cases": initial_rows}, sort_keys=True) + "\n", encoding="utf-8")
    product_map_path = root / "product-map.json"
    product_map_path.write_text(json.dumps({"schema": "ds02.stage2.root-nine-gencase-product-map.v2",
                                             "status": "COMPLETED", "products": product_rows}, sort_keys=True) + "\n", encoding="utf-8")
    return initial_path, product_map_path, data_root, actual_receipts


def _write_bad_map(path: Path, original: dict[str, Any], mutate: str) -> Path:
    value = json.loads(json.dumps(original))
    if mutate == "duplicate":
        value["products"].append(dict(value["products"][0]))
    elif mutate == "partial":
        value["products"] = value["products"][:-1]
    elif mutate == "failed":
        value["products"][0]["status"] = "FAILED_RUNTIME_PRODUCER"
    elif mutate == "producer_sha":
        value["products"][0]["producer_request"]["sha256"] = "0" * 64
    else:
        raise AssertionError(mutate)
    out = path.with_name(f"bad-{mutate}.json")
    out.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _real_runtime_fixture_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="native-header-v6-runtime-", dir=HERE) as td:
        root = Path(td)
        producer, control, launcher, decoder = _write_runtime_fixture(root)
        initial_path, product_map_path, data_root, receipts = _fixture_rows(root, launcher, producer, control)
        source_gate = validate_source_rows(initial_path, product_map_path)
        if source_gate["state"] != "READY" or not source_gate["ready"] or source_gate["rows"] != 9:
            raise AssertionError(f"actual shared runner rows did not become READY: {source_gate}")
        result = build(initial_path, product_map_path, decoder, root / "v6-output")
        if result["v6_gate"]["state"] != "READY" or result["status"] != "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V6":
            raise AssertionError(f"V6 build did not preserve explicit terminal readiness: {result}")
        manifest = _small_json(Path(result["manifest"]), "V5 manifest")[0]
        if len(manifest.get("cases", [])) != 9:
            raise AssertionError("V5 output did not contain nine exact cases")

        # A failed producer is obtained from the same actual runner, not from
        # a hand-written receipt.  The gate must reject it as a concrete
        # failure rather than silently counting its product row.
        failed_case = "tiny_failure_case"
        failed_attempt = "attempt_failure"
        failed_req_path = root / "failed-request.json"
        _make_producer_request(failed_req_path, producer, control, "F2", failed_case, failed_attempt, root, fail=True)
        failed_receipt = _run_actual_runner(launcher, failed_req_path, data_root, "F2", failed_case, failed_attempt)
        if failed_receipt.get("status") != "failed" or failed_receipt.get("returncode") == 0:
            raise AssertionError(f"actual runner did not preserve failed producer status: {failed_receipt}")
        original_map = _small_json(product_map_path, "fixture product map")[0]
        for mutate, expected in (("duplicate", "REJECTED"), ("failed", "REJECTED"), ("producer_sha", "REJECTED"), ("partial", "WAITING")):
            bad_map = _write_bad_map(root / "fixture-map-source.json", original_map, mutate)
            observed = validate_source_rows(initial_path, bad_map)
            if observed["state"] != expected:
                raise AssertionError(f"V6 {mutate} gate state {observed['state']!r}, expected {expected}: {observed}")

        # Relative auxiliary control is part of the producer contract.  A
        # real runner invocation from the wrong cwd must fail, not be treated
        # as a successful producer because the absolute input hash was valid.
        wrong_req_path = root / "wrong-cwd-request.json"
        wrong_cwd = root / "wrong-cwd"
        wrong_cwd.mkdir()
        _make_producer_request(wrong_req_path, producer, control, "F2", "tiny_wrong_cwd", "attempt_wrong_cwd", wrong_cwd)
        wrong_receipt = _run_actual_runner(launcher, wrong_req_path, data_root, "F2", "tiny_wrong_cwd", "attempt_wrong_cwd")
        if wrong_receipt.get("status") != "failed" or wrong_receipt.get("returncode") == 0:
            raise AssertionError(f"relative forcing/cwd mismatch was not rejected: {wrong_receipt}")


def self_test() -> None:
    _real_runtime_fixture_self_test()
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V6_REAL_RUNNER_TERMINAL_GATE_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--initial-manifest", type=Path)
    parser.add_argument("--initial-request", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V6_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    required = (args.initial_manifest, args.product_map, args.decoder, args.output_dir)
    if any(value is None for value in required):
        parser.error("--build requires --initial-manifest, --product-map, --decoder, and --output-dir")
    try:
        result = build(args.initial_manifest, args.product_map, args.decoder, args.output_dir,
                       args.initial_request, args.admission_manifest)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V6: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "manifest": result["manifest"],
                      "request": result["request"], "v6_gate": result["v6_gate"],
                      "production_payload_read": False, "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
