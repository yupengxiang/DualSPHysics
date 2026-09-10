"""Analytic translation through the real HDF5 observation path; not CFD."""
import json
import tempfile
from pathlib import Path
import h5py
import numpy as np
from scripts.l1r_f3_metrics import observe

LOW = np.array([-.45, -.09, 0.])
SIZE = np.array([.9, .18, .09])
EDGES = [np.arange(-.45,.451,.06), np.arange(-.09,.091,.06), np.r_[np.arange(0,.51,.06),.51]]


def main():
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for shift in [0., .006, .06, .54]:
            hists = []
            for dp in [.015, .01, .0075, .006]:
                axes = [LOW[k]+(np.arange(round(SIZE[k]/dp))+.5)*dp for k in range(3)]
                p = np.stack(np.meshgrid(*axes, indexing='ij'),axis=-1).reshape(-1,3)
                p[:,2] += shift
                path = Path(folder)/'analytic.h5'
                with h5py.File(path,'w') as h:
                    h['time'] = [0.]
                    h['position'] = p[None]
                    h['velocity'] = np.zeros_like(p)[None]
                    h['mass'] = np.full((1,len(p)),1000*dp**3)
                    h['valid'] = np.ones((1,len(p)),dtype=bool)
                actual = observe({}, [0.], path=path)[0]
                lo = LOW + [0,0,shift]
                hi = lo + SIZE
                fractions = [np.maximum(0,np.minimum(e[1:],hi[k])-np.maximum(e[:-1],lo[k]))/SIZE[k] for k,e in enumerate(EDGES)]
                truth = np.einsum('i,j,k->ijk',*fractions).ravel()
                truth = np.r_[truth, 1-truth.sum(), 0.]
                com_error = float(np.linalg.norm(actual['com']-(lo+SIZE/2)))
                assert com_error < 1e-10
                assert abs(actual['hist'].sum()-1) < 1e-12
                if shift == .54:
                    assert abs(actual['hist'][-2]-1) < 1e-12
                rows.append(dict(shift_z_m=shift,dp_m=dp,n=len(p),
                                 tv_to_exact=float(.5*np.abs(actual['hist']-truth).sum()),
                                 com_error_m=com_error,outside_fraction=float(actual['hist'][-2])))
                hists.append(actual['hist'])
            pair = float(.5*np.abs(hists[0]-hists[1]).sum())
            if shift == .006:
                assert abs(pair-1/9) < 1e-12
    result = dict(kind='manufactured quadrature; real observe() executed; no CFD',
                  cases=rows,checks_passed=True,
                  conclusion='Point-count TV has sampling error comparable to the 0.05 budget; historical gates remain unchanged.',
                  incomplete=['rotation','volume-preserving deformation','origin and scale sensitivity','held-out negative controls','v2 calibration'])
    out = Path(__file__).with_name('registered-observe-calibration.json')
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
