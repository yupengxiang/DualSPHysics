"""Reassemble an identical bundle using transferred metadata and local hashed data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_package import verify_bundle
from scripts.core_runtime import digest, atomic_json


def relocate(metadata_root, data_root, destination):
    metadata, data, destination = map(lambda p: Path(p).resolve(),
                                       (metadata_root, data_root, destination))
    if destination.exists():
        raise FileExistsError('immutable bundle destination exists')
    index = json.loads((metadata/'bundle.json').read_text())
    staging = destination.with_name(destination.name+'.staging-'+uuid.uuid4().hex)
    staging.mkdir(parents=True)
    reused = copied = 0
    try:
        for item in index['files']:
            relative = Path(item['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('bundle path escapes root')
            source = (metadata/relative).resolve()
            source.relative_to(metadata)
            local_asset = not source.is_file()
            if local_asset:
                source = (data/relative).resolve()
                source.relative_to(data)
            if digest(source) != item['sha256']:
                raise ValueError(f'relocation source hash mismatch: {relative}')
            target = staging/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            if local_asset:
                os.link(source,target)
                reused += item['bytes']
            else:
                shutil.copyfile(source,target)
                copied += item['bytes']
        shutil.copyfile(metadata/'bundle.json',staging/'bundle.json')
        verified = verify_bundle(staging)
        os.rename(staging,destination)
        return {'schema':'core.bundle_relocation.v1','passed':verified['passed'],
                'bundle_index_sha256':digest(destination/'bundle.json'),
                'destination':str(destination),'copied_bytes':copied,
                'reused_hardlink_bytes':reused,'full_core_release':False,
                'model_prediction_reproduced':False}
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('metadata-root','data-root','destination','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=relocate(args.metadata_root,args.data_root,args.destination)
    atomic_json(args.output,result)
    print(json.dumps(result))
