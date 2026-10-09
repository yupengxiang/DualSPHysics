from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_copied_dependency_inventory_v58.py"
V4 = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v4.py"
PLAIN = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
CONVERTER = ROOT / "scripts/ds_data02_f5_bi4.py"
V14 = ROOT / "scripts/ds_data02_stage2_f2_replay_v14.py"
V15 = ROOT / "scripts/ds_data02_stage2_f2_replay_v15.py"
V16 = ROOT / "scripts/ds_data02_stage2_f2_flux_v16.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Path]]:
    bundle = tmp_path / "bundle"
    sources = bundle / "sources"
    native = bundle / "runtime" / "runtime" / "native"
    sources.mkdir(parents=True)
    native.mkdir(parents=True)
    wrapper = sources / V4.name
    plain = native / PLAIN.name
    shutil.copyfile(V4, wrapper)
    shutil.copyfile(PLAIN, plain)
    aliases = {}
    for role, source in {
        "raw_converter": CONVERTER,
        "v14_operator": V14,
        "v15_operator": V15,
        "v16_operator": V16,
    }.items():
        target = sources / source.name
        shutil.copyfile(source, target)
        aliases[role] = target
    decoder = sources / "0023-bi4_dump"
    shutil.copyfile(DECODER, decoder)
    decoder.chmod(stat.S_IMODE(DECODER.stat().st_mode))
    return bundle, wrapper, plain, aliases | {"decoder": decoder}


def test_v58_cli_records_actual_import_and_payload_boundaries(tmp_path):
    bundle, wrapper, plain, files = _bundle(tmp_path)
    output = tmp_path / "v58-inventory.json"
    command = [str(PYTHON), str(SCRIPT),
               "--bundle-root", str(bundle), "--wrapper", str(wrapper),
               "--plain-worker", str(plain), "--decoder", str(files["decoder"]),
               "--output", str(output)]
    for role in ("raw_converter", "v14_operator", "v15_operator", "v16_operator"):
        command.extend(["--alias", f"{role}={files[role]}"])
    completed = subprocess.run(command, capture_output=True, text=True,
                               check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text())
    assert report["status"] == "PASS_SOURCE_ONLY_COPIED_DEPENDENCY_INVENTORY"
    scope = report["executed_binary_and_interface_scope"]
    assert scope["payload_read"] is False
    assert scope["decoder"]["executed"] is False
    assert "converter.convert_direct" in scope["not_executed"]
    interfaces = report["module_interfaces"]
    assert interfaces["plain_worker_v2"]["module_load_imports"] == ["h5py", "numpy"]
    assert interfaces["plain_worker_v2"]["module_load_opens_hdf5"] is False
    assert interfaces["v14_operator"]["hdf5_import_deferred"] is True
    assert interfaces["v15_operator"]["delegates_hdf5_reads_to_v14"] is True
    assert interfaces["v16_operator"]["hdf5_import_present"] is False
    assert interfaces["v16_operator"]["json_forward_entrypoint"] is True
