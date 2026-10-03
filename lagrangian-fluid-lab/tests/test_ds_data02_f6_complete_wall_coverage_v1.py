from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_f6_centered_wall_initial_v1 import face_coverage


def wall():
    xyz=np.stack(np.meshgrid(np.arange(4),np.arange(3),np.arange(3),indexing='ij'),axis=-1).reshape(-1,3)
    chosen=(xyz[:,0]==0)|(xyz[:,0]==3)|(xyz[:,1]==0)|(xyz[:,1]==2)|(xyz[:,2]==0)
    return xyz[chosen].astype(float)*.5


def test_five_complete_faces():
    report=face_coverage(wall(),.5)
    assert report['all_five_faces_complete']
    assert report['faces']['y_high']['expected_points']==12


def test_positive_edges_do_not_prove_a_wall_face():
    xyz=wall()
    hole=(xyz[:,1]==1)&(xyz[:,0]>.0)&(xyz[:,0]<1.5)&(xyz[:,2]>.0)
    broken=xyz[~hole]
    report=face_coverage(broken,.5)
    assert all(x['actual_points']>0 for x in report['faces'].values())
    assert not report['faces']['y_high']['complete']
    assert not report['all_five_faces_complete']
