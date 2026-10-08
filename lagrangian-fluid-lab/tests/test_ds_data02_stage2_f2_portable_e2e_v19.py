from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V19_SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_parent_supplemental_charge_v19.py"
SUPERVISOR = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_external_supervisor_v19.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V19 = _load("f2_supplemental_v19_e2e", V19_SCRIPT)
SUP = _load("f2_supervisor_v19_e2e", SUPERVISOR)


def _write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(value, bytes) else "w"
    with path.open(mode) as stream:
        stream.write(value)


def _json(path: Path, value: dict) -> None:
    _write(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def _fake_runtime(path: Path) -> None:
    _write(
        path,
        textwrap.dedent(
            """
            import json
            from contextlib import contextmanager
            from pathlib import Path

            @contextmanager
            def ledger_locked(data_root):
                ledger_path = Path(data_root) / "resource-ledger" / "resource-ledger.json"
                value = json.loads(ledger_path.read_text())
                yield value
                ledger_path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\\n")
            """,
        ).lstrip(),
    )


def _fixture(tmp_path: Path) -> dict[str, Path | dict]:
    data_root = tmp_path / "data"
    ledger_path = data_root / "resource-ledger" / "resource-ledger.json"
    external = tmp_path / "external"
    home = tmp_path / "home"
    external.mkdir()
    home.mkdir()
    runtime = tmp_path / "fake_runtime.py"
    _fake_runtime(runtime)

    attempt = "manufactured-f2-v19-attempt"
    ledger = {
        "limits": {
            "storage_policy": "home_free_floor",
            "home_path": str(home),
            "home_min_free_bytes": 0,
            "new_storage_bytes": 1,
            "cpu_core_seconds": 100.0,
        },
        "charges": [{
            "id": attempt,
            "status": "completed",
            "cpu_core_seconds": 0.1,
            "new_storage_bytes": 0,
        }],
        "reservations": [],
    }
    _json(ledger_path, ledger)

    bridge_path = tmp_path / "fake-v10-bridge.json"
    v11_path = tmp_path / "fake-v11-launch.json"
    v13_path = tmp_path / "fake-v13-launch.json"
    trace_path = external / "os-open-trace-v19.log"
    sidecar_path = external / "os-open-trace-v19-finalization-v13.json"
    helper_request = external / "v19-helper-request.json"
    fake_bridge = tmp_path / "fake_bridge.py"
    fake_launcher = tmp_path / "fake_launcher.py"
    receipt_path = tmp_path / "home-receipt.json"

    _json(bridge_path, {
        "schema": "manufactured.v10",
        "guard_bindings": [{
            "role": "shared_runtime_v6",
            "path": str(runtime),
            "sha256": V19.sha256_file(runtime),
        }],
    })
    _json(v11_path, {"schema": "manufactured.v11", "bridge_request": {"path": str(bridge_path)}})

    v13 = {
        "schema": "ds02.stage2.f2-parent-supervised-launch.v13",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "attempt_id": attempt,
        "accounting": {
            "ledger_path": str(ledger_path),
            "attempt_id": attempt,
            "home_receipt_path": str(tmp_path / "home-receipt.json"),
        },
        "parent_resource_binding": {
            "limits": {"home_path": str(home), "deadline_utc": None},
        },
        "storage_scope": {
            "external_filesystem": str(external),
            "finalization_sidecar": str(sidecar_path),
            "home_min_free_bytes": 0,
        },
        "trace": {"path": str(trace_path)},
        "execution": {"trace_finalization_sidecar": str(sidecar_path)},
        "v11_launch": {"path": str(v11_path)},
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    v13["sha256"] = V19.canonical_sha(v13)
    _json(v13_path, v13)

    # The fake launcher has the same --request/--parent-pid surface used by
    # the real v13 supervisor.  It stands in for the native bridge only; no
    # HDF5/BI4 or CFD input is touched.
    _write(
        fake_bridge,
        textwrap.dedent(
            f"""
            import json
            from pathlib import Path
            trace = Path({str(trace_path)!r})
            sidecar = Path({str(sidecar_path)!r})
            receipt = Path({str(receipt_path)!r})
            request = json.loads(Path({str(v13_path)!r}).read_text())
            trace.write_bytes(b"trace-final")
            receipt.write_text(json.dumps({{"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                "filesystem": {{"artifact_check": {{"items": [
                    {{"role": "parent_os_open_trace", "path": str(trace), "bytes": 4}}
                ]}}}}}}) + "\\n")
            value = {{
                "schema": "ds02.stage2.f2-parent-trace-finalization.v13",
                "request_sha256": request["sha256"],
                "attempt_id": {attempt!r},
                "trace": {{"path": str(trace), "bytes": trace.stat().st_size,
                          "bridge_receipt_trace_bytes": 4,
                          "trace_growth_after_bridge_charge_bytes": trace.stat().st_size - 4}},
                "cleanup": {{"fake_bridge_terminal": True}},
                "supplemental_charge_required": True,
                "model_invoked": False, "cfd_invoked": False,
                "qualification": {{"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            }}
            body = dict(value)
            body.pop("sha256", None)
            import hashlib
            value["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True,
                separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
            sidecar.write_text(json.dumps(value, sort_keys=True, indent=2) + "\\n")
            print(json.dumps({{"status": "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN",
                              "model_invoked": False, "cfd_invoked": False}}))
            """,
        ).lstrip(),
    )
    _write(
        fake_launcher,
        textwrap.dedent(
            f"""
            import argparse, subprocess, sys
            p = argparse.ArgumentParser()
            sub = p.add_subparsers(dest="command", required=True)
            run = sub.add_parser("run")
            run.add_argument("--request", required=True)
            run.add_argument("--parent-pid", required=True)
            args = p.parse_args()
            result = subprocess.run([sys.executable, {str(fake_bridge)!r}], check=False,
                                    text=True, capture_output=True)
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(result.returncode)
            """,
        ).lstrip(),
    )
    return {
        "data_root": data_root,
        "ledger": ledger_path,
        "external": external,
        "runtime": runtime,
        "v13": v13_path,
        "helper_request": helper_request,
        "fake_launcher": fake_launcher,
        "trace": trace_path,
        "sidecar": sidecar_path,
        "receipt": receipt_path,
    }


def test_fake_launcher_trace_helper_and_supervisor_charge_are_cli_compatible(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    launch = subprocess.run(
        [str(PYTHON), "-B", str(fixture["fake_launcher"]), "run",
         "--request", str(fixture["v13"]), "--parent-pid", str(os.getpid())],
        check=False, text=True, capture_output=True,
    )
    assert launch.returncode == 0, launch.stderr
    assert json.loads(launch.stdout)["status"].startswith("COMPLETED_")
    assert fixture["trace"].is_file() and fixture["sidecar"].is_file()

    build = subprocess.run(
        [str(PYTHON), "-B", str(V19_SCRIPT), "build-request",
         "--v13-request", str(fixture["v13"]), "--output", str(fixture["helper_request"])],
        check=False, text=True, capture_output=True,
    )
    assert build.returncode == 0, build.stderr
    applied = subprocess.run(
        [str(PYTHON), "-B", str(V19_SCRIPT), "apply", "--request", str(fixture["helper_request"])],
        check=False, text=True, capture_output=True,
    )
    assert applied.returncode == 0, applied.stderr
    result = json.loads(applied.stdout)
    assert result["status"] == "SUPPLEMENTAL_CHARGE_APPLIED"
    assert result["bytes"]["bridge_trace_source"] == "v10_terminal_receipt"
    assert result["charge"]["new_storage_bytes"] == fixture["trace"].stat().st_size - 4 + fixture["sidecar"].stat().st_size

    # The final supervisor charge uses the same parent runtime/ledger API.  It
    # is deliberately called after the fake terminal and helper charge, so a
    # missing parent terminal or active reservation cannot be hidden by a
    # successful strace/child exit.
    runtime_sha = V19.sha256_file(fixture["runtime"])
    charged = SUP._charge_wrapper(
        fixture["runtime"], runtime_sha, fixture["ledger"],
        "manufactured-f2-v19-attempt::supervisor-v19",
        "manufactured-f2-v19-attempt", external=fixture["external"],
        bytes_count=17, cpu_seconds=0.05, status="completed", max_cpu=100.0,
        reservation_id=None, allow_missing_parent=False,
        home_path=fixture["data_root"].parent / "home", home_floor=0, external_floor=0,
    )
    assert charged["status"] == "SUPERVISOR_CHARGE_APPLIED"
    ledger = json.loads(fixture["ledger"].read_text())
    ids = {row["id"] for row in ledger["charges"]}
    assert "manufactured-f2-v19-attempt::v13-trace-finalization-v19" in ids
    assert "manufactured-f2-v19-attempt::supervisor-v19" in ids


def test_supervisor_stops_only_the_owned_process_group(tmp_path: Path) -> None:
    child = subprocess.Popen([str(PYTHON), "-c", "import time; time.sleep(30)"],
                             start_new_session=True)
    result = SUP._stop_group(child, grace=0.2)
    assert result["sigterm_sent"] is True
    assert result["reaped"] is True
    assert child.poll() is not None
