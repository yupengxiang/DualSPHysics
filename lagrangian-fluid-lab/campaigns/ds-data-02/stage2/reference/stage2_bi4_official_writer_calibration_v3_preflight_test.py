#!/usr/bin/env python3
"""Exercise the real V3 ``--run`` source-manifest gate without compiling.

The test builds a fresh V3 manifest from small repository sources, removes the
V3 worker record, and invokes the actual worker entry point with ``--run``.
The expected result is the bounded, nonzero source-closure failure before any
compiler or manufactured payload is started.  It therefore catches undefined
run-local closure names such as the V2 ``WORKER`` failure while remaining
source-only.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
BUILDER_PATH = HERE / "stage2_bi4_official_writer_calibration_request_v3.py"
WORKER_PATH = HERE / "stage2_bi4_official_writer_calibration_worker_v3.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    builder = _load(BUILDER_PATH, "stage2_bi4_official_writer_calibration_request_v3_preflight")
    with tempfile.TemporaryDirectory(prefix="stage2-root214-v3-preflight-") as tmp_name:
        tmp = Path(tmp_name)
        request_path = tmp / "request.json"
        manifest_path = tmp / "manifest.json"
        builder.build(
            output_request=request_path,
            output_manifest=manifest_path,
            case_id="F1_BI4_OFFICIAL_WRITER_CALIBRATION_ROOT214_PREFLIGHT",
            attempt_id="f1-bi4-official-writer-calibration-root214-preflight",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_files"] = [
            record
            for record in manifest["source_files"]
            if not str(record["path"]).endswith(WORKER_PATH.name)
        ]
        bad_manifest = tmp / "manifest-missing-worker.json"
        bad_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        attempt = tmp / "attempt"
        output = attempt / "report.json"
        command = [
            sys.executable,
            "-B",
            str(WORKER_PATH),
            "--run",
            "--source-manifest",
            str(bad_manifest),
            "--attempt-root",
            str(attempt),
            "--output",
            str(output),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 2:
            raise AssertionError(f"expected source-closure exit 2, got {result.returncode}: {result.stderr}")
        if "omits required calibration closure" not in result.stderr:
            raise AssertionError(f"real --run preflight did not reject missing worker: {result.stderr}")
        if "NameError" in result.stderr:
            raise AssertionError(f"real --run still has an undefined closure symbol: {result.stderr}")
        if output.exists():
            report = json.loads(output.read_text(encoding="utf-8"))
            if report.get("status") != "FAILED_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER_V3":
                raise AssertionError(f"unexpected failure report: {report}")
    print(json.dumps({"status": "PASS", "real_run_preflight": "missing_worker_rejected_before_compile"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
