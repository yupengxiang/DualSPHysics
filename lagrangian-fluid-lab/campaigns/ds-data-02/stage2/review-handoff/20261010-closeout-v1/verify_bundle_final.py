"""Check both original evidence and additive final-report metadata."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

def verify(p):
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))
        for name in z.namelist():
            n=PurePosixPath(name)
            assert not n.is_absolute() and '..' not in n.parts
        index=json.loads(z.read('EVIDENCE_INDEX.json'))
        rows=index['files']+json.loads(z.read('ADDITIONAL_FILES.json'))['files']
        for v in rows:
            b=z.read(v['member'])
            assert len(b)==v['bytes'] and hashlib.sha256(b).hexdigest()==v['sha256'],v['member']
        assert index['portable_raw_replay_bundle'] is False
        print(json.dumps({'status':'PASS_FINAL_REVIEW_PACKAGE_CRC_SHA256',
            'evidence_files':len(index['files']),'additional_files':len(rows)-len(index['files']),
            'scientific_arrays_verified':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('zip',type=Path)
    verify(p.parse_args().zip)
