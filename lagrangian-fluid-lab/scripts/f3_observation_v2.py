"""Conservative fixed-scale observations for a plain rectangular tank only.

This operator measures kernel-averaged distributions, not pointwise CFD truth.
The tent half-width is fixed in metres, independent of solver particle spacing.
Solid walls truncate and normalize each particle's kernel; the open top does not.
Particles already outside the tank remain outside, and missing mass is explicit.
"""
import numpy as np
from scipy.sparse import csr_matrix

LOW = np.array([-.45, -.09, 0.])
HIGH = np.array([.45, .09, .51])
U = np.sqrt(9.81*.09)


def edges_for(width=.06, origin_shift=0.):
    return [np.unique(np.r_[lo, np.arange(lo+origin_shift, hi, width)[
        (np.arange(lo+origin_shift, hi, width)>lo)], hi]) for lo,hi in zip(LOW,HIGH)]


def tent_cdf(s):
    s = np.asarray(s)
    return np.where(s <= -1, 0., np.where(s < 0, .5*(s+1)**2,
                    np.where(s < 1, 1-.5*(1-s)**2, 1.)))


def axis_weights(x, edges, axis, bandwidth):
    w = np.diff(tent_cdf((edges[None]-x[:,None])/bandwidth), axis=1)
    # x/y are closed on both ends; z has a closed bottom and an open top.
    norm = ((tent_cdf((HIGH[axis]-x)/bandwidth) if axis < 2 else 1.)
            -tent_cdf((LOW[axis]-x)/bandwidth))
    return w/norm[:,None]


def observe_arrays(p, v, m, initial_mass, *, bandwidth=.06, cell_width=.06,
                   origin_shift=0.):
    p, v, m = np.asarray(p,float), np.asarray(v,float), np.asarray(m,float)
    if p.shape != v.shape or p.shape != (len(m),3):
        raise ValueError('incompatible state arrays')
    if not all(np.isfinite(x).all() for x in (p,v,m)) or np.any(m <= 0):
        raise ValueError('finite state and positive mass required')
    if initial_mass <= 0 or m.sum() > initial_mass*(1+1e-10):
        raise ValueError('invalid initial mass denominator')
    edges = edges_for(cell_width, origin_shift)
    shape = tuple(len(e)-1 for e in edges)
    bins = np.zeros(shape)
    momentum = np.zeros((*shape,3))
    inside = np.all((p >= LOW)&(p <= HIGH),axis=1)
    selected = np.flatnonzero(inside)
    for start in range(0,len(selected),32768):
        ix = selected[start:start+32768]
        weights = [axis_weights(p[ix,k],edges[k],k,bandwidth) for k in range(3)]
        xy = csr_matrix((weights[0][:,:,None]*weights[1][:,None,:]).reshape(len(ix),-1)).T
        bins += (xy @ (weights[2]*m[ix,None])).reshape(shape)
        for k in range(3):
            momentum[...,k] += (xy @ (weights[2]*(m[ix]*v[ix,k])[:,None])).reshape(shape)
    hist = np.r_[bins.ravel(), m.sum()-bins.sum(), initial_mass-m.sum()]/initial_mass
    order = np.argsort(p[:,0])
    q90 = float(np.interp(.9*m.sum(), np.cumsum(m[order]), p[order,0])) if len(m) else None
    return dict(hist=hist, momentum=momentum.reshape(-1,3)/initial_mass,
                com=np.average(p,axis=0,weights=m) if len(m) else np.full(3,np.nan),
                q90=q90, mean_velocity=np.average(v,axis=0,weights=m) if len(m) else np.full(3,np.nan),
                energy_normalized=float(np.sum(m*np.sum(v*v,axis=1))/(initial_mass*U*U)),
                mass_fraction=float(m.sum()/initial_mass))


def compare(a,b):
    ma,mb = a['hist'][:-2], b['hist'][:-2]
    support = (ma > 1e-10)&(mb > 1e-10)
    velocity = np.zeros_like(ma)
    velocity[support] = np.linalg.norm(a['momentum'][support]/ma[support,None]
                                       - b['momentum'][support]/mb[support,None],axis=1)
    return dict(tv=float(.5*np.abs(a['hist']-b['hist']).sum()),
                com_l2_over_length=float(np.linalg.norm(a['com']-b['com'])/.9),
                q90_over_length=abs(a['q90']-b['q90'])/.9,
                mean_velocity_over_U=float(np.linalg.norm(a['mean_velocity']-b['mean_velocity'])/U),
                energy_difference=abs(a['energy_normalized']-b['energy_normalized']),
                common_support_velocity_over_U=float(np.sum(np.minimum(ma,mb)*velocity)/U),
                unmatched_support_mass=float(np.sum(np.maximum(ma,mb)[~support])))
