#!/usr/bin/env python3
"""Build a relocatable reader bundle, without claiming a complete Core release."""
from __future__ import annotations
import argparse
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_dataset import CoreDataset
from scripts.core_cfd_dataset import open_dataset
from scripts.core_runtime import atomic_json, digest


CHECKPOINT_REGISTRY_SCHEMA = 'core.bundled_checkpoints.v1'


def _validate_checkpoint_registry(root, report, seen):
    """Validate optional model assets without turning packaging into training."""
    if 'checkpoints.json' not in seen:
        return 0
    registry_path = root / 'checkpoints.json'
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('invalid checkpoint registry') from error
    if registry.get('schema') != CHECKPOINT_REGISTRY_SCHEMA:
        raise ValueError('unsupported checkpoint registry version')
    rows = registry.get('checkpoints')
    if not isinstance(rows, list) or not rows:
        raise ValueError('checkpoint registry must contain at least one checkpoint')
    file_rows = {item['path']: item for item in report['files']}
    paths = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('malformed checkpoint registry entry')
        path = row.get('path')
        if (not isinstance(path, str) or not path or Path(path).is_absolute()
                or '..' in Path(path).parts):
            raise ValueError('checkpoint registry path is not portable')
        if path in paths or path not in seen or path not in file_rows:
            raise ValueError('checkpoint registry path is missing or duplicated')
        paths.add(path)
        sha = row.get('sha256')
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError('checkpoint registry hash is malformed')
        try:
            int(sha, 16)
        except ValueError as error:
            raise ValueError('checkpoint registry hash is malformed') from error
        if file_rows[path]['sha256'].lower() != sha.lower():
            raise ValueError('checkpoint registry hash disagrees with bundle artifact')
        if not isinstance(row.get('model_kind'), str) or not row['model_kind']:
            raise ValueError('checkpoint registry model_kind is missing')
        if isinstance(row.get('seed'), bool) or not isinstance(row.get('seed'), int):
            raise ValueError('checkpoint registry seed is malformed')
        if (isinstance(row.get('update'), bool) or not isinstance(row.get('update'), int)
                or row['update'] < 0):
            raise ValueError('checkpoint registry update is malformed')
    return len(rows)


def verify_bundle(directory):
    """Verify every registered artifact, including code, before reproduction."""
    root = Path(directory).resolve()
    report = json.loads((root / 'bundle.json').read_text())
    if report.get('schema') != 'core.reader_bundle.v1':
        raise ValueError('unsupported bundle version')
    seen = set()
    for item in report['files']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in seen:
            raise ValueError('invalid or duplicate bundle artifact path')
        seen.add(str(relative))
        target = (root / relative).resolve()
        target.relative_to(root)
        if not target.is_file() or target.stat().st_size != item['bytes'] or digest(target) != item['sha256']:
            raise ValueError(f'bundle artifact integrity failure: {relative}')
    required = {'dataset.json', 'environment.json', 'code/scripts/core_benchmark.py',
                'code/scripts/core_cfd_dataset.py', 'code/scripts/core_learning.py',
                'code/scripts/core_models.py', 'code/scripts/core_evaluation.py',
                'code/scripts/core_contract.py', 'code/scripts/core_physics.py',
                'code/scripts/core_reproduction_check.py'}
    if not required <= seen:
        raise ValueError('bundle is missing required artifact registrations')
    checkpoint_count = _validate_checkpoint_registry(root, report, seen)
    declared_count = report.get('checkpoint_count', 0)
    if (isinstance(declared_count, bool) or not isinstance(declared_count, int)
            or declared_count != checkpoint_count):
        raise ValueError('bundle checkpoint count disagrees with registry')
    return {'passed': True, 'verified_files': len(seen), 'full_core_release': False,
            'checkpoint_count': checkpoint_count,
            'model_reproduction_supported': bool(checkpoint_count)}


def build_bundle(manifest, data_root, destination, *, hardlink=False, checkpoint_manifest=None):
    manifest, root, destination = Path(manifest), Path(data_root).resolve(), Path(destination).absolute()
    if destination.exists():
        raise FileExistsError("bundle destination already exists; immutable publication required")
    assets = {}
    checkpoints = []
    if checkpoint_manifest is not None:
        checkpoint_source = json.loads(Path(checkpoint_manifest).read_text())
        for index, item in enumerate(checkpoint_source.get('checkpoints', [])):
            source = Path(item['path'])
            source = (source if source.is_absolute() else root/source).resolve()
            source.relative_to(root)
            relative = f'models/checkpoint-{index:03d}.pt'
            assets[relative] = {'sha256':item['sha256'],'source':source}
            checkpoints.append({'path':relative,'sha256':item['sha256'],
                                'model_kind':item['model_kind'],'seed':item['seed'],
                                'update':item['update']})
        if not checkpoints:
            raise ValueError('checkpoint manifest must register at least one checkpoint')
    with open_dataset(manifest, root) as data:
        # Publish the normalized public contract so a CFD source manifest does
        # not retain a runtime dependency on its original preparation directory.
        payload = copy.deepcopy(data.manifest)
        for case_id in data.case_ids():
            row = data.record(case_id)
            data.known_inputs(case_id)
            references = [{"path":row["hdf5"], "sha256":row["sha256"]}]
            references += [v for k,v in row.get("known_inputs_ref",{}).items() if k in ("geometry","control")]
            for ref in references:
                relative = Path(ref["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("bundle assets must use portable relative paths")
                source = (root / relative).resolve()
                source.relative_to(root)
                if relative.as_posix() in assets and assets[relative.as_posix()]["sha256"] != ref["sha256"]:
                    raise ValueError("conflicting content hashes for a shared asset")
                assets[relative.as_posix()] = {"sha256":ref["sha256"], "source":source}
        for row in payload['cases']:
            provenance = row.get('provenance', {})
            prepared = provenance.get('prepared')
            if isinstance(prepared, str):
                source = Path(prepared)
                source = (source if source.is_absolute() else root/source).resolve()
                relative = source.relative_to(root).as_posix()
                assets[relative] = {'sha256':digest(source),'source':source}
                provenance['prepared'] = relative
                provenance['prepared_sha256'] = assets[relative]['sha256']
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = destination.with_name(destination.name + ".staging-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        files = []
        for relative, ref in sorted(assets.items()):
            source, target = ref["source"], staging / relative
            if digest(source) != ref["sha256"]:
                raise ValueError(f"source integrity failure: {relative}")
            target.parent.mkdir(parents=True,exist_ok=True)
            if hardlink:
                os.link(source,target)
            else:
                shutil.copyfile(source,target)
            if digest(target) != ref["sha256"]:
                raise ValueError(f"transfer integrity failure: {relative}")
            files.append({"path":relative,"sha256":ref["sha256"],"bytes":target.stat().st_size})
        atomic_json(staging/'dataset.json',payload)
        files.append({"path":"dataset.json","sha256":digest(staging/'dataset.json'),
                      "bytes":(staging/'dataset.json').stat().st_size})
        if checkpoints:
            atomic_json(staging/'checkpoints.json',{'schema':'core.bundled_checkpoints.v1',
                'checkpoints':checkpoints,'formal_training_qualification':'not_inferred_from_packaging'})
            files.append({'path':'checkpoints.json','sha256':digest(staging/'checkpoints.json'),
                          'bytes':(staging/'checkpoints.json').stat().st_size})
        code_root = staging/'code/scripts'
        code_root.mkdir(parents=True)
        (code_root/'__init__.py').write_text('')
        for name in ('core_benchmark.py','core_runtime.py','core_contract.py','core_dataset.py',
                     'core_models.py','core_learning.py','core_cfd_dataset.py','core_package.py',
                     'core_evaluation.py','core_physics.py','core_reproduction_check.py',
                     'passive_tracers.py','f3_control.py'):
            source = Path(__file__).resolve().parent/name
            target = code_root/name
            shutil.copyfile(source,target)
            compile(target.read_text(),str(target),'exec')
            files.append({'path':str(target.relative_to(staging)),'sha256':digest(target),'bytes':target.stat().st_size})
        versions = {name:importlib.metadata.version(name) for name in ('numpy','scipy','h5py','torch')}
        atomic_json(staging/'environment.json',{'python':sys.version,'observed_packages':versions,
                    'note':'Recorded build environment; choose the torch CUDA wheel for the target host. No environment is modified.'})
        (staging/'README.md').write_text(
            '# Core development reader bundle\n\n'
            'From this directory, run:\n\n'
            '```sh\n'
            'python code/scripts/core_package.py --verify-bundle .\n'
            'python code/scripts/core_benchmark.py verify --manifest dataset.json --data-root .\n'
            '# With a registered checkpoint and explicitly selected cases:\n'
            'python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . '
            '--checkpoint models/checkpoint-000.pt --case-id CASE_ID --output-dir ../reproduction\n'
            '```\n\n'
            'The reader path needs NumPy, SciPy and h5py. Checkpoint-backed model reproduction additionally needs PyTorch.\n'
            'Build versions are recorded in environment.json. Full product reproduction requires a paired report from a distinct host.\n'
            'This bundle is not a completed or scientifically qualified Core release.\n')
        for relative in ('code/scripts/__init__.py','environment.json','README.md'):
            target=staging/relative
            files.append({'path':relative,'sha256':digest(target),'bytes':target.stat().st_size})
        report = {"schema":"core.reader_bundle.v1", "full_core_release":False,
                  "scope":"registered dataset, public inputs, code and optionally hash-bound model checkpoints; scientific qualification remains separate",
                  "checkpoint_count":len(checkpoints),
                  "case_count":len(payload['cases']),"files":files,
                  "physical_storage":"shared hardlinks; do not mutate source or bundle" if hardlink else "independent copies",
                  "entrypoint":"python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root .",
                  "model_reproduction_supported":bool(checkpoints),
                  "model_entrypoint":"python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . --checkpoint models/checkpoint-000.pt --case-id CASE_ID --output-dir ../reproduction"}
        atomic_json(staging/'bundle.json',report)
        verify_bundle(staging)
        # Rename publishes only a fully copied and verified directory.
        os.rename(staging,destination)
        return report
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-bundle',type=Path,help='verify an existing immutable bundle without rebuilding')
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--data-root',type=Path)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--checkpoint-manifest',type=Path,help='optional registered checkpoint paths, hashes and model identities')
    parser.add_argument('--hardlink',action='store_true')
    parser.add_argument('--verify-reader',action='store_true')
    parser.add_argument('--source-host')
    args=parser.parse_args()
    if args.verify_bundle is not None:
        if any((args.manifest,args.data_root,args.destination,args.checkpoint_manifest,args.hardlink,args.verify_reader,args.source_host)):
            parser.error('--verify-bundle cannot be combined with build options')
        print(json.dumps(verify_bundle(args.verify_bundle),indent=2))
        return 0
    if not all((args.manifest,args.data_root,args.destination)):
        parser.error('building requires --manifest, --data-root and --destination')
    report=build_bundle(args.manifest,args.data_root,args.destination,hardlink=args.hardlink,
                        checkpoint_manifest=args.checkpoint_manifest)
    if args.verify_reader:
        destination=args.destination.resolve()
        verify_bundle(destination)
        command=[sys.executable,str(destination/'code/scripts/core_benchmark.py'),'reproduce',
                 '--manifest',str(destination/'dataset.json'),'--data-root',str(destination),
                 '--output',str(destination/'reader-reproduction.json')]
        if args.source_host:
            command.extend(['--source-host',args.source_host])
        env=dict(os.environ)
        env.pop('PYTHONPATH',None)
        subprocess.run(command,cwd=destination,env=env,check=True)
        verification=json.loads((destination/'reader-reproduction.json').read_text())
        if not verification['passed']:
            return 1
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
