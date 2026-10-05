#!/usr/bin/env python3
"""Verify the fresh078 source package without consuming future products."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSEMBLER = ROOT / "scripts/assemble_post_conversion_pipeline.py"
METADATA = ROOT / "scripts/verify_post_conversion_metadata.py"
CONTRACT = ROOT / "pipeline-contract.json"
FORBIDDEN_IMPORTS = {"h5py", "numpy", "np", "subprocess", "paraview"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["source_only"] is True
    assert contract["arrays_opened_by_source_prep"] is False
    assert contract["jobs_started_by_source_prep"] is False
    assert contract["full801_authorized"] is False
    assert contract["cpu_task_kinds"] == {"typed_conversion": "conversion", "xmf": "audit", "bed_audit": "audit", "render": "preview"}
    for path in (ASSEMBLER, METADATA):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] in FORBIDDEN_IMPORTS for alias in node.names), (path, node.lineno)
            if isinstance(node, ast.ImportFrom):
                assert node.module not in FORBIDDEN_IMPORTS, (path, node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"Popen", "run", "system"}, (path, node.lineno)
    assert "H5" in ASSEMBLER.read_text(encoding="utf-8")
    print(json.dumps({
        "schema": "ds02.f5.b071.fresh078.source-verification.v1",
        "status": "metadata_ast_pass",
        "source_only": True,
        "arrays_opened": False,
        "jobs_started": False,
        "full801_authorized": False,
        "cpu_task_kinds_allowlisted": True,
        "assembler_sha256": sha(ASSEMBLER),
        "metadata_verifier_sha256": sha(METADATA),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
