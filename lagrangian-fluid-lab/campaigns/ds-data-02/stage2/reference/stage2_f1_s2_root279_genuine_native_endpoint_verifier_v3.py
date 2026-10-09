#!/usr/bin/env python3
"""Run the genuine manufactured ROOT279 observer chain.

The older ROOT279 fixture exercised the guarded wrapper and endpoint consumer,
but its child worker copied a prewritten JSON report.  This additive fixture
closes that interface gap without changing any consumed source: it creates two
tiny native source sets, invokes the frozen ``stage2_native_physical_observer_v2``
through its real CLI and manufactured decoder, adapts those actual decoded
observations to the ROOT279 endpoint schema, and then invokes the independent
ROOT279 V2 verifier.

All files are temporary manufactured fixtures.  No production BI4, VTK, HDF5,
solver output, or scientific reference is read.  The resulting chain is still
diagnostic-only: QI/QN/QE remain UNKNOWN and no interpolation or neighboring
grid truth is introduced.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
NATIVE = HERE / "stage2_native_physical_observer_v2.py"
GUARDED = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
V4 = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
COMMON = HERE / "stage2_f1_s2_root279_common_endpoint_observer_v1.py"
VERIFY = HERE / "stage2_f1_s2_root279_pair_report_verify_v2.py"

PAIR_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
PAIR_STATUS = "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT"
GUARD_SCHEMA = "ds02.stage2.f1-s2.root279-native-observer-guarded.v1"
GUARD_STATUS = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
CHILD_SCHEMA = "ds02.stage2.f1.native-selected-observer.v1"
CHILD_STATUS = GUARD_STATUS
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
PROOF_SCHEMA = "ds02.stage2.root-actual-external-solver-verification.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3"
REQUEST_STATUS = "READY_FOR_PARENT_V8_F1_S2_ROOT279_PAIR_NATIVE_OBSERVER_V3"
QUERY_TIMES = (0.0, 0.25, 0.5)
SELECTED_FRAMES = (0, 49, 50, 99, 100)
MODES = ("same_cfl", "half_cfl")
JSON_CAP = 10 * 1024 * 1024


class FixtureFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FixtureFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _record(path: Path) -> dict[str, Any]:
    path = path.absolute()
    return {"path": str(path), "sha256": _sha(path), "stat": _stat(path)}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FixtureFailure(f"refuse to overwrite fixture file: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _runparts(path: Path) -> None:
    # The native worker uses the actual saved rows to form its brackets.  Only
    # the five selected Part files are manufactured; the other rows are small
    # CSV metadata and are never treated as native payload.
    rows = ["Part;TimeStep [s]"] + [f"{frame};{frame * 0.005:.12f}" for frame in range(101)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_decoder(source: Path, executable: Path) -> None:
    # The source text deliberately contains the frozen bi4_dump argc/output
    # contract checked by the physical observer.  The executable consumes the
    # manufactured Part bytes and emits the same XML/array names as the real
    # adapter, plus a tiny header sidecar used only by this fixture adapter.
    source.write_text(
        "// manufactured adapter contract: if(argc!=3)return 2;\n"
        "// LoadFile(argv[1]); SaveFileXml(std::string(argv[2])+\".xml\"); dump(d,argv[2]);\n",
        encoding="utf-8",
    )
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, struct, sys\n"
        "frame_path = pathlib.Path(sys.argv[1]); prefix = pathlib.Path(sys.argv[2])\n"
        "raw = frame_path.read_bytes()\n"
        "if not raw.startswith(b'ROOT279-TINY-PART-'):\n"
        "    raise SystemExit('manufactured decoder input marker missing')\n"
        "frame = int(frame_path.stem.split('_')[-1]); time_s = frame * 0.005\n"
        "data = prefix / 'PART_0000'; data.mkdir(parents=True, exist_ok=True)\n"
        "ids = (0, 1, 2, 3)\n"
        "pos = (frame * 0.001, 0.0, 0.0, 1.0 + frame * 0.001, 0.0, 0.0, 2.0 + frame * 0.001, 0.0, 0.0, 3.0 + frame * 0.001, 0.0, 0.0)\n"
        "vel = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 3.0, 0.0, 0.0)\n"
        "rho = (1000.0, 1000.0, 1000.0, 1000.0)\n"
        "(data / 'Idp.bin').write_bytes(struct.pack('<4I', *ids))\n"
        "(data / 'Posd.bin').write_bytes(struct.pack('<12d', *pos))\n"
        "(data / 'Vel.bin').write_bytes(struct.pack('<12f', *vel))\n"
        "(data / 'Rhop.bin').write_bytes(struct.pack('<4f', *rho))\n"
        "prefix.with_suffix('.xml').write_text(f'''<root><item name=\"JPartDataBi4\"><double name=\"MassFluid\" v=\"0.5\"/><double name=\"MassBound\" v=\"1.0\"/><double name=\"Dp\" v=\"0.01\"/><int name=\"Npiece\" v=\"1\"/><int name=\"Piece\" v=\"0\"/><int name=\"NpDynamic\" v=\"0\"/><int name=\"ReuseIds\" v=\"0\"/><int name=\"PeriMode\" v=\"0\"/><item name=\"PART_0000\"><double name=\"TimeStep\" v=\"{time_s}\"/></item></item></root>''', encoding='utf-8')\n"
        "header_root = os.environ.get('ROOT279_TINY_HEADER_ROOT')\n"
        "if header_root:\n"
        "    target = pathlib.Path(header_root); target.mkdir(parents=True, exist_ok=True)\n"
        "    (target / f'{frame:04d}.json').write_text(json.dumps({'frame': frame, 'header': {'MassFluid': {'value': 0.5, 'unit': 'kg'}, 'MassBound': {'value': 1.0, 'unit': 'kg'}, 'Dp': {'value': 0.01, 'unit': 'm'}}, 'decoder_input_bytes': len(raw)}) + '\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _make_case(root: Path, label: str) -> dict[str, Any]:
    case_root = root / label
    raw_root = case_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    for frame in SELECTED_FRAMES:
        (raw_root / f"Part_{frame:04d}.bi4").write_bytes(f"ROOT279-TINY-PART-{label}-{frame}".encode("ascii"))
    runparts = case_root / "RunPARTs.csv"
    _runparts(runparts)
    generated_xml = case_root / "generated.xml"
    generated_xml.write_text(
        "<case><execution><particles>"
        '<fixed begin="0" count="2" mk="10" />'
        '<fluid begin="2" count="2" mkfluid="0" mk="1" />'
        "</particles></execution><constants>"
        '<massfluid value="0.5" /><massbound value="1.0" /><rhop0 value="1000" />'
        '</constants><gravity x="0" y="0" z="-9.81" /></case>\n',
        encoding="utf-8",
    )
    decoder_source = case_root / "bi4_dump.cpp"
    decoder = case_root / "bi4_dump"
    _write_decoder(decoder_source, decoder)
    records = {
        str(raw_root / f"Part_{frame:04d}.bi4"): {
            "path": str(raw_root / f"Part_{frame:04d}.bi4"),
            "frame": frame,
            "bytes": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_size),
            "mtime_ns": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_mtime_ns),
            "sha256": _sha(raw_root / f"Part_{frame:04d}.bi4"),
            "known_sha256": _sha(raw_root / f"Part_{frame:04d}.bi4"),
            "stat_at_prepare": {
                "bytes": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_size),
                "mtime_ns": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_mtime_ns),
                "ctime_ns": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_ctime_ns),
                "device": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_dev),
                "inode": int((raw_root / f"Part_{frame:04d}.bi4").stat().st_ino),
            },
        }
        for frame in SELECTED_FRAMES
    }
    return {
        "label": label,
        "identity": {"sentinel_id": "F1-S2", "family_id": "F1", "grid": "medium", "cfl_mode": label, "physical_case_id": f"fixture-{label}"},
        "raw_root": str(raw_root),
        "runparts": str(runparts),
        "generated_xml": str(generated_xml),
        "decoder": str(decoder),
        "decoder_source": str(decoder_source),
        "expected_frame_count": 101,
        "expected_final_time_s": 0.5,
        "selected_frames": list(SELECTED_FRAMES),
        "selected_native_frame_paths": [str(raw_root / f"Part_{frame:04d}.bi4") for frame in SELECTED_FRAMES],
        "selected_native_frame_metadata": records,
        "query_times": list(QUERY_TIMES),
        "scratch_root": "{attempt_root}/scratch/" + label,
        "old_observer_provenance": {},
    }


def _make_guard_manifest(root: Path, cases: list[dict[str, Any]]) -> Path:
    records: dict[str, Any] = {}
    for case in cases:
        records.update(case["selected_native_frame_metadata"])
    manifest = {
        "schema": "ds02.stage2.f1.native-selected-observer-manifest.v2",
        "status": "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT",
        "axis_authority": {"coordinate_contract": {"status": "MANUFACTURED_FIXTURE_ONLY"}},
        "cases": cases,
        "native_deferred_records": records,
    }
    path = root / "guard-manifest.json"
    _write(path, manifest)
    return path


def _write_child_worker(path: Path) -> None:
    # This is a real child process used by the frozen ROOT279 guard.  It calls
    # the frozen physical observer twice; it does not copy a prepared child
    # JSON.  The adapter only reshapes the observer's compact output for the
    # existing common endpoint contract.
    native = str(NATIVE)
    python = str(PYTHON)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, hashlib, json, os, pathlib, subprocess, sys\n"
        f"NATIVE = pathlib.Path({native!r})\n"
        f"PYTHON = pathlib.Path({python!r})\n"
        "p=argparse.ArgumentParser(); p.add_argument('--manifest', required=True); p.add_argument('--attempt-root', required=True); p.add_argument('--output', required=True); a=p.parse_args()\n"
        "manifest=json.loads(pathlib.Path(a.manifest).read_text(encoding='utf-8'))\n"
        "cases=[]\n"
        "for case in manifest['cases']:\n"
        "    label=case['label']; attempt=pathlib.Path(a.attempt_root); observer=attempt/'observer'/(label+'-physical.json'); headers=attempt/'observer'/(label+'-headers'); scratch=pathlib.Path(case['scratch_root'].replace('{attempt_root}', str(attempt.resolve()), 1))\n"
        "    env=dict(os.environ); env['ROOT279_TINY_HEADER_ROOT']=str(headers)\n"
        "    command=[str(PYTHON), '-B', str(NATIVE), '--raw-root', case['raw_root'], '--runparts', case['runparts'], '--generated-xml', case['generated_xml'], '--decoder', case['decoder'], '--decoder-source', case['decoder_source'], '--output', str(observer), '--scratch-root', str(scratch), '--expected-frame-count', str(case['expected_frame_count']), '--expected-final-time-s', str(case['expected_final_time_s']), '--frames', *[str(x) for x in case['selected_frames']], '--query-times', *[str(x) for x in case['query_times']]]\n"
        "    completed=subprocess.run(command, cwd=str(pathlib.Path(a.manifest).parent), env=env, capture_output=True, text=True, timeout=120)\n"
        "    if completed.returncode != 0 or not observer.is_file(): raise SystemExit('frozen physical observer failed: '+completed.stdout[-1000:]+completed.stderr[-1000:])\n"
        "    physical=json.loads(observer.read_text(encoding='utf-8'))\n"
        "    if physical.get('status') != 'PASS_DECODED_SELECTED_NATIVE_FIELDS': raise SystemExit('physical observer did not pass: '+str(physical.get('status')))\n"
        "    selected=[]\n"
        "    for observation in physical['observations']:\n"
        "        frame=int(observation['frame']); header_path=headers/f'{frame:04d}.json'\n"
        "        header=json.loads(header_path.read_text(encoding='utf-8'))['header']\n"
        "        fluid=observation['fluid_observables']; selected.append({'frame': frame, 'time_s': observation['time']['runparts_s'], 'native_header': header, 'observables': {'fluid_observable_using_native_MassFluid': {'weighted_centroid_m': fluid['centroid_m'], 'weighted_velocity_m_per_s': fluid['mean_velocity_m_per_s'], 'kinetic_energy_j': fluid['kinetic_energy_j'], 'mass_semantics': 'native decoder MassFluid header; weighted from frozen physical observer'}, 'physical_observer_status': physical['status']}, 'native_observer_fields': {'raw_field_digest_sha256': observation['raw_field_digest_sha256'], 'decoder_xml_sha256': observation['decoder_xml_sha256'], 'finite_fields': observation['finite_fields'], 'identity': observation['identity']}})\n"
        "    queries=[]\n"
        "    for query in physical['time_window']['queries']:\n"
        "        queries.append({'query_time_s': query['query_time_s'], 'status': query['status'], 'lower_frame': query['lower_frame'], 'upper_frame': query['upper_frame'], 'lower_time_s': query['lower_time_s'], 'upper_time_s': query['upper_time_s']})\n"
        "    cases.append({'label': label, 'identity': case['identity'], 'time': {'queries': queries, 'interpolation': 'NOT_PERFORMED'}, 'selected_observations': selected, 'physical_observer': {'path': str(observer), 'sha256': hashlib.sha256(observer.read_bytes()).hexdigest(), 'schema': physical['schema'], 'status': physical['status'], 'scope': physical['scope']}})\n"
        "pathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True)\n"
        "pathlib.Path(a.output).write_text(json.dumps({'schema':'ds02.stage2.f1.native-selected-observer.v1','status':'PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES','cases':cases,'production_payload_read':False,'scientific_qualification':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN','credit':0},'adapter_scope':'manufactured decoder output reshaped from actual frozen physical observer; no interpolation'}, sort_keys=True), encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _snapshot_and_pair(root: Path, guard: dict[str, Any], cases: list[dict[str, Any]]) -> tuple[Path, Path, list[dict[str, Any]]]:
    pre = guard.get("source_integrity", {}).get("pre")
    if not isinstance(pre, list) or len(pre) != 10:
        raise FixtureFailure("guard did not return ten source records")
    by_path = {str(Path(item["path"]).absolute()): item for item in pre}
    selected: list[dict[str, Any]] = []
    for case in cases:
        for frame in SELECTED_FRAMES:
            path = str(Path(case["raw_root"]) / f"Part_{frame:04d}.bi4")
            item = by_path.get(str(Path(path).absolute()))
            if item is None:
                raise FixtureFailure(f"guard source record missing {path}")
            stat = item["stat"]
            selected.append({
                "path": str(Path(path).absolute()), "frame": frame, "bytes": int(stat["bytes"]), "sha256": item["sha256"],
                "stat_before": {"bytes": int(stat["bytes"]), "mtime_ns": int(stat["mtime_ns"]), "ctime_ns": int(stat["ctime_ns"]), "st_dev": int(stat["device"]), "st_ino": int(stat["inode"])},
                "stat_after": {"bytes": int(stat["bytes"]), "mtime_ns": int(stat["mtime_ns"]), "ctime_ns": int(stat["ctime_ns"]), "st_dev": int(stat["device"]), "st_ino": int(stat["inode"])},
                "stat_consistency": "PASS_PRE_POST_IDENTICAL",
            })
    immutable = [{key: item[key] for key in ("frame", "path", "bytes", "sha256")} for item in selected]
    snapshot = {
        "schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS,
        "worker_scope": {"bi4_decode": False, "solver_launch": False},
        "requests": [{"selected_native_files": selected[:5]}, {"selected_native_files": selected[5:]}],
        "immutable_source_sha_list": immutable,
        "source_sha_list_digest": hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "selected_native_total_bytes": sum(item["bytes"] for item in selected),
    }
    snapshot_path = root / "snapshot.json"; _write(snapshot_path, snapshot)
    pair_cases = []
    for index, case in enumerate(cases):
        subset = selected[index * 5:(index + 1) * 5]
        pair_cases.append({
            "label": case["label"],
            "selected_native_frame_metadata": [{
                "path": item["path"], "frame": item["frame"], "known_sha256": item["sha256"],
                "stat_at_prepare": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]},
            } for item in subset],
        })
    pair_path = root / "pair.json"; _write(pair_path, {"schema": PAIR_SCHEMA, "status": PAIR_STATUS, "cases": pair_cases})
    return snapshot_path, pair_path, selected


def _terminal_sources(root: Path) -> tuple[dict[str, Any], list[Path]]:
    bindings: dict[str, Any] = {}
    paths: list[Path] = []
    for label in MODES:
        request_path = root / f"{label}-producer-request.json"
        _write(request_path, {"schema": REQUEST_SCHEMA, "family_id": "F1", "case_id": f"fixture-{label}", "attempt_id": f"fixture/{label}"})
        request_record = _record(request_path)
        receipt_path = root / f"{label}-receipt.json"
        _write(receipt_path, {"schema": "ds02.execution.receipt.v1", "status": "COMPLETED_DEVELOPMENT_UNKNOWN", "request": {"path": str(request_path.absolute()), "sha256": request_record["sha256"]}, "attempt_id": f"F1/fixture-{label}/fixture", "execution": {"returncode": 0}})
        receipt_record = _record(receipt_path)
        proof_path = root / f"{label}-proof.json"
        _write(proof_path, {"schema": PROOF_SCHEMA, "status": f"VERIFIED_ACTUAL_F1_S2_DP020_{label.upper()}_NO_Q", "request": str(request_path.absolute()), "request_sha256": request_record["sha256"], "receipt": str(receipt_path.absolute()), "receipt_sha256": receipt_record["sha256"]})
        proof_record = _record(proof_path)
        bindings[label] = {"proof": str(proof_path.absolute()), "proof_sha256": proof_record["sha256"], "request": str(request_path.absolute()), "request_sha256": request_record["sha256"], "receipt": receipt_record}
        paths.extend((request_path, receipt_path, proof_path))
    return bindings, paths


def _run_chain(root: Path) -> tuple[list[Path], dict[str, Any]]:
    cases = [_make_case(root / "cases", label) for label in MODES]
    guard_manifest = _make_guard_manifest(root, cases)
    child_worker = root / "native-child-worker.py"; _write_child_worker(child_worker)
    attempt = root / "attempt"
    guard_output = attempt / "observer" / "guard.json"
    command = [str(PYTHON), "-B", str(GUARDED), "--run", "--manifest", str(guard_manifest), "--attempt-root", str(attempt), "--output", str(guard_output), "--v1-worker", str(child_worker), "--python", str(PYTHON), "--cwd", str(root), "--timeout-seconds", "120"]
    completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=150)
    if completed.returncode != 0 or not guard_output.is_file():
        raise FixtureFailure(f"ROOT279 guarded child failed rc={completed.returncode}: {completed.stdout[-1000:]} {completed.stderr[-1000:]}")
    guard = json.loads(guard_output.read_text(encoding="utf-8"))
    child_output = attempt / "observer" / ".v1-result.json"
    if guard.get("status") != GUARD_STATUS or not child_output.is_file():
        raise FixtureFailure(f"ROOT279 guard did not produce a successful child: {guard.get('status')}")
    child = json.loads(child_output.read_text(encoding="utf-8"))
    if child.get("status") != CHILD_STATUS:
        raise FixtureFailure(f"physical observer child did not pass: {child.get('status')}")

    snapshot_path, pair_path, selected = _snapshot_and_pair(root, guard, cases)
    terminal, terminal_paths = _terminal_sources(root)
    card = root / "calibration-card.json"
    bracket = lambda left, lt, right, rt, q: {"query_s": q, "left_part": left, "left_time_s": lt, "right_part": right, "right_time_s": rt}
    actual_cases = {str(item["label"]): item for item in child.get("cases", [])}
    if set(actual_cases) != set(MODES):
        raise FixtureFailure("physical observer child did not return both ROOT279 cases")
    observed_brackets: dict[str, list[dict[str, Any]]] = {}
    for label in MODES:
        observed_brackets[label] = [
            bracket(int(query["lower_frame"]), float(query["lower_time_s"]), int(query["upper_frame"]), float(query["upper_time_s"]), float(query["query_time_s"]))
            for query in actual_cases[label]["time"]["queries"]
        ]
    card_value = {"schema": "ds02.stage2.f1-s2.common-endpoint-calibration.v1", "frozen_tolerances": {"position_fraction_of_registered_L": {"value": 0.02, "measured": False}, "velocity_and_ke_fraction_of_registered_nonzero_scale": {"value": 0.05, "measured": False}, "time_and_output_each_fraction_of_task_tolerance": {"value": 0.25, "measured": False}}, "observed_brackets": observed_brackets}
    _write(card, card_value)
    root279_manifest = root / "root279-manifest.json"
    _write(root279_manifest, {"schema": PAIR_SCHEMA, "status": PAIR_STATUS, "cases": [{"label": case["label"], "selected_frames": list(SELECTED_FRAMES), "identity": case["identity"]} for case in cases]})
    root279_result = root / "root279-result.json"
    _write(root279_result, guard)
    child_record = _record(child_output)
    pair_record = _record(pair_path); snapshot_record = _record(snapshot_path)
    common_manifest = root / "common-manifest.json"
    cases_manifest = [{"label": case["label"], "identity": case["identity"], "control_binding": {"effective_CFL": 0.2 if case["label"] == "same_cfl" else 0.1, "TimeMax_s": 0.5, "output_interval_s": 0.005}, "brackets": card_value["observed_brackets"][case["label"]]} for case in cases]
    _write(common_manifest, {"schema": "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1", "status": "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1", "query_times_s": list(QUERY_TIMES), "query_policy": {"interpolation": False, "extrapolation": False}, "frozen_tolerances": card_value["frozen_tolerances"], "sources": {"calibration_card": _record(card), "root279_manifest": pair_record, "root279_guard_result": _record(guard_output), "root279_child_report": child_record}, "cases": cases_manifest})
    common = _load(COMMON, "stage2_root279_common_native_fixture")
    common_output = root / "common-output.json"
    endpoint = common.run(common_manifest, common_output)
    if endpoint.get("status") != "COMPLETE_F1_S2_ROOT279_COMMON_ENDPOINT_DIAGNOSTICS_NO_SCIENTIFIC_Q":
        raise FixtureFailure(f"common endpoint rejected actual native observer output: {endpoint}")
    static_paths = [card, root279_manifest, snapshot_path, pair_path, guard_output, child_output, common_manifest, common_output, *terminal_paths, NATIVE, GUARDED, COMMON, VERIFY]
    input_records = {str(path.absolute()): _record(path) for path in static_paths}
    request_path = root / "pair-request.json"
    request = {"schema": REQUEST_SCHEMA, "variant_schema": REQUEST_VARIANT, "status": REQUEST_STATUS, "execution_allowed": False, "launch_disabled": False, "input_files": sorted(input_records), "input_records": input_records, "input_sha256": {path: record["sha256"] for path, record in input_records.items()}, "manifest": pair_record, "deferred_input_records": [{"path": item["path"], "frame": item["frame"], "known_sha256": item["sha256"], "stat_at_prepare": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]}} for item in selected], "source_binding": {"queries_s": list(QUERY_TIMES), "interpolation": "FORBIDDEN", "root277_terminal": terminal["same_cfl"], "root278_terminal": terminal["half_cfl"], "root310_snapshot": snapshot_record}, "native_payload_read": False, "solver_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
    _write(request_path, request)
    verifier = _load(VERIFY, "stage2_root279_pair_report_v2_for_genuine_fixture")
    verified = verifier.verify(common_manifest, common_output, pair_path, request_path, snapshot_path, guard_output, child_output)
    if verified.get("status") != "VERIFIED_ROOT279_PAIR_REPORT_METADATA_ONLY_V2":
        raise FixtureFailure(f"independent V2 verifier returned unexpected status: {verified.get('status')}")
    return [common_manifest, common_output, pair_path, request_path, snapshot_path, guard_output, child_output], verified


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-genuine-native-v3-") as directory:
        root = Path(directory)
        paths, verified = _run_chain(root)
        if verified["scientific_qualification"]["credit"] != 0:
            raise FixtureFailure("genuine manufactured chain granted scientific credit")
        # A missing native header is a real adapter failure, not a fallback to
        # XML mass.  This is deliberately tested after the successful chain.
        child = json.loads(paths[-1].read_text(encoding="utf-8"))
        child["cases"][0]["selected_observations"][0].pop("native_header")
        bad_child = root / "bad-child.json"; _write(bad_child, child)
        bad_common = root / "bad-common.json"
        common = _load(COMMON, "stage2_root279_common_native_negative")
        manifest = json.loads(paths[0].read_text(encoding="utf-8")); manifest["sources"]["root279_child_report"] = _record(bad_child); _write(bad_common, manifest)
        # Missing MassFluid is an allowed diagnostic outcome, but must remain
        # UNKNOWN rather than silently falling back to XML mass.
        missing_result = common.run(bad_common, root / "bad-common-output.json")
        missing_status = missing_result["cases"][0]["queries"][0]["fields"]["weighted_centroid_m"]["status"]
        if missing_status != "UNKNOWN_NATIVE_MASSFLUID_MISSING":
            raise FixtureFailure("missing native header did not remain UNKNOWN")
        # The independent verifier must reject a post-chain child mutation
        # through the common source SHA join, rather than trusting case labels.
        shutil.copyfile(paths[1], root / "bad-output.json")
        bad_output = json.loads((root / "bad-output.json").read_text(encoding="utf-8")); bad_output["scientific_qualification"]["credit"] = 1; (root / "bad-output.json").write_text(json.dumps(bad_output), encoding="utf-8")
        verifier = _load(VERIFY, "stage2_root279_pair_report_v2_negative")
        try:
            verifier.verify(paths[0], root / "bad-output.json", paths[2], paths[3], paths[4], paths[5], paths[6])
        except Exception:
            pass
        else:
            raise FixtureFailure("tampered endpoint output was accepted")
    print("PASS_ROOT279_V3_GENUINE_NATIVE_OBSERVER_ENDPOINT_VERIFIER_CHAIN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.error("--self-test is the only source-only mode")
    try:
        self_test()
    except Exception as exc:
        print(f"FAILED_ROOT279_V3_GENUINE_NATIVE_CHAIN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
