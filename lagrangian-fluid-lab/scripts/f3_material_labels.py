"""Unknown-aware residence labels and same-seed temporal diagnostics."""
import json
from pathlib import Path
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256


def labels(path):
    a=dict(np.load(path));p=a['position'];ok=a['reliable'];dt=np.diff(a['time'])
    x0,x1=p[:-1,:,0],p[1:,:,0]
    bothleft=(x0<0)&(x1<0);crossed=(x0<0)!=(x1<0)
    alpha=np.divide(-x0,x1-x0,out=np.zeros_like(x0),where=crossed)
    fraction=np.where(bothleft,1.,np.where(crossed,np.where(x0<0,alpha,1-alpha),0.))
    known=ok[:-1]&ok[1:]
    residence_left=np.sum(dt[:,None]*fraction*known,axis=0)
    residence_right=np.sum(dt[:,None]*(1-fraction)*known,axis=0)
    residence_unknown=np.sum(dt[:,None]*~known,axis=0)
    assert np.allclose(residence_left+residence_right+residence_unknown,a['time'][-1]-a['time'][0],atol=1e-12)
    a.update(residence_left_s=residence_left,residence_right_s=residence_right,residence_unknown_s=residence_unknown)
    output=path.with_name(path.stem+'-labels.npz');np.savez_compressed(output,**a)
    by_source={}
    for source in (0,1):
        mask=a['source_label']==source;w=a['weight'];den=w[mask].sum()
        by_source[str(source)]={
            'initial_mass_fraction':float(den),
            'terminal_left_right_unknown':[float(w[mask&(a['terminal_label']==k)].sum()/den) for k in (0,1,2)],
            'first_passage_fraction':float(w[mask&np.isfinite(a['first_passage_s'])].sum()/den),
            'mean_residence_left_right_unknown_s':[float(np.sum(w[mask]*v[mask])/den) for v in (residence_left,residence_right,residence_unknown)],
        }
    return a,dict(artifact=str(output.relative_to(LAB)),sha256=sha256(output),by_source=by_source)


def main():
    manifests=[json.loads((OUT/f'F3-MATERIAL-ENGINEERING-s{s}.json').read_text()) for s in (2,4)]
    for m in manifests:
        if m['status']!='completed' or sha256(LAB/m['artifact'])!=m['artifact_sha256']:
            raise ValueError('material source is incomplete or changed')
    a,ma=labels(LAB/manifests[0]['artifact']);b,mb=labels(LAB/manifests[1]['artifact'])
    assert np.array_equal(a['initial_position'],b['initial_position']) and np.array_equal(a['time'],b['time'])
    common=a['reliable']&b['reliable'];error=np.linalg.norm(a['position']-b['position'],axis=-1)
    events=np.isfinite(a['first_passage_s'])&np.isfinite(b['first_passage_s'])
    report=dict(scope='engineering temporal consistency only; no source spatial reference or T2 qualification',
        configurations=[ma,mb],same_initial_points=True,
        failure_denominator=512,
        common_reliable_fraction=float(common.mean()),
        maximum_same_seed_path_difference_m=float(error[common].max()) if common.any() else None,
        maximum_first_passage_time_difference_s=float(np.abs(a['first_passage_s'][events]-b['first_passage_s'][events]).max()) if events.any() else None,
        first_passage_classification_disagreement_fraction=float(np.mean(np.isfinite(a['first_passage_s'])!=np.isfinite(b['first_passage_s']))),
        terminal_classification_disagreement_fraction=float(np.mean(a['terminal_label']!=b['terminal_label'])),
        maximum_residence_time_difference_s=max(float(np.abs(a[k]-b[k]).max()) for k in ('residence_left_s','residence_right_s','residence_unknown_s')),
        unknown_not_renormalized=True,
        remaining=['qualified source','cross-dp same-initial-point path reference','hard endpoint','manufactured and held-out path reconstruction'])
    write('F3-MATERIAL-ENGINEERING-COMPARISON.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
