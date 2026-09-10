"""Conservative saved-state distance bound for the optional fourth layer."""
import json
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.f3_boundary_support_preflight import points
from scripts.l1r_q2_mdbc_bridge import sha256


def main():
    base='F3_CELL3_plain_0p01'
    oldpath=LAB/'campaigns/l1-resume/artifacts/cell3'/base/(base+'_Bound.vtk')
    pre=json.loads((OUT/'F3-BOUNDARY4-INPUT-PREFLIGHT.json').read_text());prefix=LAB/pre['candidate_prefix']
    newpath=prefix.with_name(prefix.name+'_Bound.vtk')
    old={tuple(p) for p in points(oldpath)};added=np.array([p for p in points(newpath) if tuple(p) not in old])
    kernel_radius=2*.91924*np.sqrt(3)*.01
    rows=[]
    for variant in ('noslip_visco1','noslip_visco1_time','noslip_visco1_time_quarter'):
        name='F3_CELL3_LONG_dp0p01_a1p000_'+variant;a=json.loads((OUT/(name+'-AUDIT.json')).read_text());source=LAB/a['hdf5']
        if sha256(source)!=a['hdf5_sha256']:raise ValueError('changed audited source')
        lower=np.full(3,np.inf);upper=-lower
        with h5py.File(source) as h:
            for i in range(len(h['time'])):
                p=h['position'][i][h['valid'][i]].astype(float)
                lower=np.minimum(lower,p.min(axis=0));upper=np.maximum(upper,p.max(axis=0))
        closest=np.maximum(lower,np.minimum(added,upper));bound=np.linalg.norm(added-closest,axis=-1)
        rows.append(dict(case=name,source_sha256=a['hdf5_sha256'],all_saved_fluid_aabb_m=[lower.tolist(),upper.tolist()],minimum_new_boundary_to_aabb_distance_m=float(bound.min()),kernel_radius_m=kernel_radius,all_added_particles_outside_saved_fluid_kernel_support=bool(bound.min()>kernel_radius)))
    result=dict(added_boundary_particles=len(added),boundary_vtk_hashes=[sha256(oldpath),sha256(newpath)],rows=rows,
        interpretation='Distance to enclosing AABB is a lower bound on distance to every saved fluid point and its linear inter-frame chord. If above kernel support, added particles have no direct fluid-kernel contribution at those states.',limitations=['unsaved native integration stages are not bounded by saved states','indirect implementation/cell-order effects are not ruled out','this does not certify any wall or recipe'],decision='Do not treat the generic DDT warning alone as evidence that a fourth layer will fix residual crossings; prioritize spatial diagnostics after the temporal trend failed.')
    write('F3-BOUNDARY4-COUPLING-PREFLIGHT.json',result);print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
