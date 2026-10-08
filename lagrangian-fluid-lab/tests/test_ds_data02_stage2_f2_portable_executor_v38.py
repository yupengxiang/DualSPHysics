from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v38.py"
SPEC = importlib.util.spec_from_file_location("portable_executor_v38_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v38 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v38)

PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _module_fixture(tmp_path: Path) -> tuple[Path, dict[str, dict[str, str]]]:
    worker_dir = tmp_path / "copied" / "sources"
    worker_dir.mkdir(parents=True)
    names = {
        "v14_operator": "0026-ds_data02_stage2_f2_replay_v14.py",
        "v15_operator": "0027-ds_data02_stage2_f2_replay_v15.py",
        "v16_operator": "0028-ds_data02_stage2_f2_flux_v16.py",
    }
    (worker_dir / names["v14_operator"]).write_text("VALUE = 14\n")
    (worker_dir / names["v15_operator"]).write_text(
        "import ds_data02_stage2_f2_replay_v14 as v14\nVALUE = v14.VALUE + 1\n"
    )
    (worker_dir / names["v16_operator"]).write_text("VALUE = 16\n")
    bindings = {}
    for role, name in names.items():
        path = worker_dir / name
        bindings[role] = {
            "role": role,
            "path": str(path),
            "sha256": v38.sha256_file(path),
            "bytes": str(path.stat().st_size),
        }
    worker = worker_dir / "0029-worker.py"
    worker.write_text(
        "import ds_data02_stage2_f2_replay_v15 as v15\n"
        "print('worker-value', v15.VALUE)\n"
    )
    return worker, bindings


def test_aliases_and_isolated_import_are_target_only(tmp_path: Path) -> None:
    worker, bindings = _module_fixture(tmp_path)
    aliases = v38._materialize_aliases(bindings, worker.parent)
    assert {item["state"] for item in aliases} == {"CREATED_FROM_COPIED_SOURCE"}
    assert all(item["inode_distinct"] for item in aliases)

    result = v38._import_subprocess(PYTHON, aliases)
    assert result["temporary_source_only"] is True
    assert result["loaded"]["v15"].endswith("ds_data02_stage2_f2_replay_v15.py")

    code, stdout, stderr = v38._run_worker_with_bootstrap(
        type("V34", (), {"_child_group_terminate": staticmethod(lambda proc: proc.kill())}),
        PYTHON, worker, tmp_path / "request.json", tmp_path / "out",
        deadline=None,
    )
    assert code == 0, stderr
    assert "worker-value 15" in stdout


def test_existing_wrong_alias_is_rejected(tmp_path: Path) -> None:
    worker, bindings = _module_fixture(tmp_path)
    wrong = worker.parent / "ds_data02_stage2_f2_replay_v14.py"
    wrong.write_text("VALUE = 999\n")
    try:
        v38._materialize_aliases(bindings, worker.parent)
    except v38.PortableV38Error as error:
        assert "canonical alias differs" in str(error)
    else:
        raise AssertionError("wrong canonical alias was accepted")


def test_import_preflight_writes_no_payload_claim(tmp_path: Path) -> None:
    worker, bindings = _module_fixture(tmp_path)
    base = tmp_path / "relocated-request.json"
    base.write_text(json.dumps({"modules": bindings}) + "\n")
    output = tmp_path / "preflight.json"
    result = v38.preflight_imports(base_request=base, python=PYTHON, output=output)
    assert result["status"] == "PASS_PRIVATE_TRANSITIVE_IMPORT_V38"
    assert result["hdf5_or_bi4_read"] is False
    assert result["raw_tree_read"] is False
    assert result["qualification"] == v38.UNKNOWN
    assert output.is_file()
