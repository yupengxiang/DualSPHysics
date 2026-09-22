"""Full-axis physical diagnostics for public state and finite static geometry."""
from __future__ import annotations
import numpy as np


def conserved_observables(state):
    active = state.valid
    mass = state.mass[active]
    total = float(mass.sum())
    return {"active_mass_kg": total, "active_particles": int(active.sum()),
            "registered_particles": state.count,
            "kinetic_energy_j": float(.5*np.sum(mass[:,None]*state.velocity[active]**2)),
            "center_of_mass_m": (np.sum(mass[:,None]*state.position[active],axis=0)/total).tolist(),
            "momentum_kg_mps": np.sum(mass[:,None]*state.velocity[active],axis=0).tolist()}


def static_wall_crossings(previous, following, geometry, *, tolerance=1e-9):
    """Intersect saved-state chords with finite triangles, never infinite planes.

    This diagnoses saved chord intersections, not unresolved substep paths.
    Moving geometry needs a separate swept-surface implementation.
    """
    if not np.array_equal(previous.particle_id,following.particle_id) or not np.array_equal(previous.particle_zone,following.particle_zone):
        raise ValueError('particle identity changed during physical evaluation')
    if np.any(geometry.wall_velocity):
        return {"status":"unsupported_moving_surface", "particle_count":None, "mass_kg":None}
    if tolerance <= 0:
        raise ValueError('positive intersection tolerance required')
    valid = previous.valid & following.valid
    origin = previous.position[valid]
    direction = following.position[valid]-origin
    hit = np.zeros(len(origin),dtype=bool)
    for triangle in geometry.triangles:
        a,b,c=triangle
        edge1,edge2=b-a,c-a
        p=np.cross(direction,edge2)
        determinant=p@edge1
        nonparallel=np.abs(determinant)>tolerance
        inverse=np.zeros_like(determinant)
        inverse[nonparallel]=1/determinant[nonparallel]
        relative=origin-a
        u=np.einsum('ij,ij->i',relative,p)*inverse
        q=np.cross(relative,edge1)
        v=np.einsum('ij,ij->i',direction,q)*inverse
        time=(q@edge2)*inverse
        hit |= nonparallel & (u>=-tolerance) & (v>=-tolerance) & (u+v<=1+tolerance) & (time>tolerance) & (time<1-tolerance)
    return {"status":"checked_static_saved_chords", "particle_count":int(hit.sum()),
            "mass_kg":float(previous.mass[valid][hit].sum()),
            "checked_particle_count":int(valid.sum()),
            "unavailable_particle_count":int((~valid).sum()),
            "semantics":"finite surface intersections of saved chords; no exact path claim"}


def frame_physics(previous, predicted, reference, geometry):
    if not np.array_equal(predicted.particle_id,reference.particle_id) or not np.array_equal(predicted.particle_zone,reference.particle_zone):
        raise ValueError('prediction/reference identities mismatch')
    observed, expected = conserved_observables(predicted), conserved_observables(reference)
    return {"predicted":observed,"reference":expected,
            "mass_error_kg":observed['active_mass_kg']-expected['active_mass_kg'],
            "kinetic_energy_error_j":observed['kinetic_energy_j']-expected['kinetic_energy_j'],
            "validity_mismatch_count":int(np.count_nonzero(predicted.valid != reference.valid)),
            "changed_particle_mass_count":int(np.count_nonzero(predicted.mass != previous.mass)),
            "wall_chord":static_wall_crossings(previous,predicted,geometry)}
