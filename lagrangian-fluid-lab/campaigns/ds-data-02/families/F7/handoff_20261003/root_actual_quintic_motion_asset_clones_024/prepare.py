import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
out = Path(a.output_dir)
out.mkdir(exist_ok=False)
motion = Path(b['motion'])
assert sha(motion) == b['motion_sha256'] and motion.stat().st_size > 0
rows = [list(map(float,line.split())) for line in motion.read_text().splitlines()
        if line and not line.startswith('#')]
assert len(rows) == 12001 and rows[0] == [0.,0.] and rows[-1] == [12.,0.]
assert all(x[0] < y[0] for x,y in zip(rows,rows[1:]))
cases = []
for c in b['cases']:
    receipt = json.loads(Path(c['gencase_receipt']).read_text())
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    d = out / c['role']
    d.mkdir()
    old = Path(c['prefix'])
    new = d / old.name
    for suffix in ['.xml','.bi4']:
        src, dst = Path(str(old)+suffix), Path(str(new)+suffix)
        assert sha(src) == c['source_hashes'][suffix]
        shutil.copyfile(src,dst)
        assert sha(dst) == c['source_hashes'][suffix]
    target = d / 'motion_obstacle_quintic.dat'
    with target.open('xb') as f:
        f.write(motion.read_bytes())
    assert sha(target) == b['motion_sha256']
    root = ET.parse(str(new)+'.xml').getroot()
    file = root.find('./execution/motion/objreal/mvrotfile/file')
    if file is None:
        file = root.find('.//mvrotfile/file')
    assert file is not None and file.get('name') == target.name
    cases.append({**c,'prefix':str(new),'actual_motion':str(target),
                  'actual_motion_sha256':sha(target),'initial_state_byte_identical':True,
                  'actual_motion_rows':len(rows)})
assert sha(motion) == b['motion_sha256']
with (out/'clone-report.json').open('x') as f:
    json.dump({'schema':'ds02.f7.actual-motion-restored-input-clones.v1','cases':cases,
               'failure_023':'GenCase output motion asset empty; three native runs stopped at initialization',
               'old_initial_QA_reuse':'Same XML and BI4 bytes, independently verified; same motion filename now backed by actual nonempty original generated file',
               'old_attempts_immutable':True,'q_n':'not_granted','production_approval':'none',
               'independent_case_count_increment':0},f,indent=2)
    f.write('\n')
