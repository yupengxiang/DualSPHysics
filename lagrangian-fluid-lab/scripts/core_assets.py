#!/usr/bin/env python3
"""Transfer explicitly registered artifacts, verify remote bytes, never sync .git."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_runtime import atomic_json, digest


def transfer(source_manifest, source_root, destination_host, destination_root, output, case_ids=None):
    manifest = json.loads(Path(source_manifest).read_text())
    root, destination = Path(source_root).resolve(), Path(destination_root)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_absolute():
        raise ValueError("explicit absolute destination root required")
    files = {}
    chosen = []
    for row in manifest["cases"]:
        if case_ids and row["case_id"] not in case_ids:
            continue
        chosen.append(row["case_id"])
        files[row["hdf5"]] = row.get("sha256") or row["file"]["sha256"]
        if "source_evidence" in row:
            for name in ("prepared", "control", "audit"):
                item = row["source_evidence"][name]
                files[item["path"]] = item["sha256"]
        for name in ("geometry", "control"):
            item = row.get("known_inputs_ref", {}).get(name)
            if item:
                files[item["path"]] = item["sha256"]
    if not chosen or (case_ids and set(chosen) != set(case_ids)):
        raise ValueError("unknown/empty requested case selection")
    try:
        manifest_relative = str(Path(source_manifest).resolve().relative_to(root))
    except ValueError:
        raise ValueError("manifest must be inside explicit source root for portable transfer")
    files[manifest_relative] = digest(source_manifest)
    for relative in files:
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not (root / relative).is_file():
            raise ValueError("invalid registered artifact path")
    file_list = output.with_suffix(".files.txt")
    file_list.write_text("".join(name + "\n" for name in sorted(files)))
    started = time.time()
    subprocess.run(["ssh", "-o", "BatchMode=yes", destination_host, shlex.join(["mkdir", "-p", str(destination)])], check=True)
    command = ["rsync", "-rt", "--partial-dir=.core-transfer", "--files-from=" + str(file_list),
               str(root) + "/", destination_host + ":" + str(destination) + "/"]
    subprocess.run(command, check=True)
    # Send data as stdin JSON; no interpolated shell/script source or credentials.
    verifier = """import sys,json,hashlib,pathlib
d=json.load(sys.stdin); root=pathlib.Path(d['root']); records=[]
for name,expected in d['files'].items():
 p=root/name; h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
 actual=h.hexdigest(); records.append({'path':name,'sha256':actual,'bytes':p.stat().st_size,'matches':actual==expected})
print(json.dumps({'passed':all(r['matches'] for r in records),'files':records}))
"""
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", destination_host,
                             shlex.join(["python3", "-c", verifier])], input=json.dumps({"root": str(destination), "files": files}),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    verified = json.loads(result.stdout)
    receipt = {"schema": "core.asset_transfer.v1", "source_manifest_sha256": digest(source_manifest),
               "destination_host": destination_host, "destination_root": str(destination), "case_ids": chosen,
               "registered_bytes": sum(x["bytes"] for x in verified["files"]), "elapsed_seconds": time.time() - started,
               "passed": verified["passed"], "files": verified["files"], "source_assets_modified": False}
    atomic_json(output, receipt)
    if not receipt["passed"]:
        raise ValueError("remote artifact hash mismatch; transfer not accepted")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination-host", required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = transfer(args.source_manifest, args.source_root, args.destination_host, args.destination_root, args.output, args.case_id)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
