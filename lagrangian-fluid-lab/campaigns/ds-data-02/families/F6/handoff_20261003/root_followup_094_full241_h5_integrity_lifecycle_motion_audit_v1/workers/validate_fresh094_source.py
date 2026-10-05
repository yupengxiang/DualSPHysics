#!/usr/bin/env python3
from pathlib import Path
import ast
import hashlib
import json

PKG = Path(__file__).resolve().parents[1]
SCIENCE = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtu", ".vtk"}

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def is_science(p):
    s = str(p).lower()
    return Path(s).suffix in SCIENCE or s.endswith("/run.out") or s.endswith("/solver_output/data") or "/solver_output/data/" in s

def check_common(d, label):
    assert d["fresh_id"] == "fresh094", label
    assert d["disabled"] is True and d["launch"] is False and d["execution_allowed"] is False, label
    assert d["future_hashes_null"] is True, label
    assert d["case_count"] == 1 and isinstance(d["case"], dict), label
    assert d["worker_sha256"] == sha(PKG / "workers/audit_f6_typed_h5_full241.py"), label
    assert set(d["input_files"]) == set(d["input_sha256"]), label
    for p, value in d["input_sha256"].items():
        assert not is_science(p), (label, p)
        assert Path(p).is_file() and value == sha(p), (label, p)
    for p, value in d.get("future_input_sha256", {}).items():
        assert value is None, (label, p)
    for key, value in d.get("future_outputs", {}).items():
        if key.endswith("_sha256"):
            assert value is None, (label, key)
    case = d["case"]
    typed_dependency = case["typed_terminal_dependency"]
    assert typed_dependency["producer_physical_condition_sha256"] is None, label
    assert typed_dependency["producer_scope_provenance"].startswith("future Root607 actual conversion-report"), label
    assert case["physical_condition_sha256"] and len(case["physical_condition_sha256"]) == 64, label
    assert case["source_plan_condition_sha256"] and len(case["source_plan_condition_sha256"]) == 64, label
    assert case["expected_native_contract"]["frames"] == 241
    assert case["expected_native_contract"]["window_s"] == [0.0, 12.0]
    assert case["expected_native_contract"]["tout_s"] == 0.05
    assert case["expected_native_contract"]["dimension"] == 3
    assert case["expected_native_contract"]["total"] == 417505
    assert case["expected_native_contract"]["vector_shape"] == [417505, 3]
    assert case["expected_native_contract"]["fixed"] == 73441
    assert case["expected_native_contract"]["fluid"] == 327680
    assert case["expected_native_contract"]["floating"] == 16384
    assert case["expected_native_contract"]["moving"] == 0
    assert case["mass_policy"]["physical_mass_kg"] == 128.0
    assert case["mass_policy"]["native_support_mass_kg"] == 256.0
    assert case["mass_policy"]["normalization"] == "none"
    assert d["binding_sha256"] == d["input_sha256"][d["binding"]]
    assert Path(d["binding"]).is_file()
    state = case["state0_dependency"]
    if state["status"] == "actual_pass":
        assert state["checks_all_pass"] is True and state["audit_status"] == "pass"
        for key in ("audit_report", "execution_receipt", "summary"):
            assert Path(state[key]).is_file()
            assert state[key + "_sha256"] == sha(state[key])
    else:
        assert state["status"] == "future_root595_adapter_required"
        assert state["checks_all_pass"] is False
        assert state["audit_report"] is None and state["execution_receipt"] is None
        assert state["observed_omega_rad_s"] is None
        assert Path(state["source_request"]).is_file() and Path(state["source_binding"]).is_file()
        assert "root582" not in json.dumps(state).lower()
    worker_text = (PKG / "workers/audit_f6_typed_h5_full241.py").read_text(encoding="utf-8")
    ast.parse(worker_text)
    assert "subprocess" not in worker_text and "os.system" not in worker_text

requests = sorted((PKG / "requests").glob("*.json"))
bindings = sorted((PKG / "bindings").glob("*.json"))
assert len(requests) == 24 and len(bindings) == 24
request_cases = set()
actual = future = 0
for path in requests:
    d = load(path)
    check_common(d, str(path))
    request_cases.add(d["case"]["case_id"])
    assert d["schema"] == "ds02.f6.fresh094.typed-h5-full241-audit-request.v1"
    if d["case"]["state0_dependency"]["status"] == "actual_pass":
        actual += 1
    else:
        future += 1
for path in bindings:
    d = load(path)
    assert d["schema"] == "ds02.f6.fresh094.typed-h5-full241-audit-binding.v1"
    assert d["fresh_id"] == "fresh094" and d["disabled"] and not d["launch"] and not d["execution_allowed"]
    assert d["future_hashes_null"] is True
    assert d["worker_sha256"] == sha(PKG / "workers/audit_f6_typed_h5_full241.py")
    for p, value in d["input_sha256"].items():
        assert not is_science(p), (str(path), p)
        assert Path(p).is_file() and value == sha(p), (str(path), p)
assert actual == 22 and future == 2
assert len(request_cases) == 24
print(json.dumps({"status": "pass", "fresh_id": "fresh094", "cases": 24, "state0_actual": actual, "state0_future": future}, indent=2))
