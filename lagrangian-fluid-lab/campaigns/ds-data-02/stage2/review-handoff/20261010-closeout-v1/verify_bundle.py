"""Verify a review ZIP without accessing any original filesystem path."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

def verify(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(set(archive.namelist()))
        for name in archive.namelist():
            p=PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts
        index=json.loads(archive.read('EVIDENCE_INDEX.json'))
        for record in index['files']:
            body=archive.read(record['member'])
            assert len(body)==record['bytes']
            assert hashlib.sha256(body).hexdigest()==record['sha256'],record['member']
        assert index['portable_raw_replay_bundle'] is False
        print(json.dumps({'status':'PASS_REVIEW_METADATA_ZIP_CRC_AND_SHA256',
            'files':len(index['files']),'scientific_array_verification':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('zip',type=Path)
    verify(p.parse_args().zip)
