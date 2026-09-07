from __future__ import annotations

import h5py
import numpy as np
import pytest

from scripts.transport_metrics import audit_transport, validate_transport_spec


def make_h5(path, moving=False):
    with h5py.File(path, "w") as h5:
        h5.attrs["case_id"] = "transport-test"
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("valid", data=[[1, 1], [1, 0]], dtype=bool)
        h5.create_dataset("type", data=[[3, 3], [3, -1]])
        h5.create_dataset("mk", data=[[0, 0], [0, -1]])
        h5.create_dataset("mass", data=[[2.0, 1.0], [2.0, np.nan]])
        position = np.zeros((2, 2, 3))
        position[1, 0] = [2.2 if moving else 0.9, 0, 0.1]
        position[1, 1] = [0.1, 0, 0.1]
        h5.create_dataset("position", data=position)
        if moving:
            transforms = np.repeat(np.eye(4)[None], 2, axis=0)
            transforms[1, 0, 3] = 2.0
            h5.create_dataset("control/receiver_world_from_body", data=transforms)


def test_missing_particle_stays_in_initial_mass_denominator(tmp_path):
    path = tmp_path / "case.h5"
    make_h5(path)
    report = audit_transport(path, {
        "lifecycle_model": "closed", "sources": {"mode": "mk"},
        "destination_frame": {"kind": "world"},
        "destinations": [{"name": "right", "type": "halfspace", "normal": [1, 0, 0],
                          "offset": 0.8, "side": "ge"}],
    })
    source = report["sources"]["0"]
    assert source["initial_mass_kg"] == pytest.approx(3.0)
    assert source["mass_fraction"]["right"] == pytest.approx(2 / 3)
    assert source["mass_fraction"]["numerical_loss"] == pytest.approx(1 / 3)
    assert source["closure_error_kg"] == pytest.approx(0.0)


def test_destination_can_be_defined_in_moving_body_frame(tmp_path):
    path = tmp_path / "case.h5"
    make_h5(path, moving=True)
    report = audit_transport(path, {
        "lifecycle_model": "closed", "sources": {"mode": "mk"},
        "destination_frame": {"kind": "moving_affine",
                              "world_from_frame_dataset": "control/receiver_world_from_body"},
        "destinations": [{"name": "receiver", "type": "aabb",
                          "min": [0.0, -0.2, 0.0], "max": [0.4, 0.2, 0.4]}],
    })
    assert report["sources"]["0"]["mass_fraction"]["receiver"] == pytest.approx(2 / 3)


def test_material_transport_is_sensitive_to_identity_permutation(tmp_path):
    """A correct point set with swapped identities must fail the transport task."""
    path = tmp_path / "identity-sensitive.h5"
    with h5py.File(path, "w") as h5:
        h5.attrs["case_id"] = "identity-sensitive"
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("valid", data=np.ones((2, 4), dtype=bool))
        h5.create_dataset("type", data=np.full((2, 4), 3, dtype=np.int8))
        # Two source groups have the same total mass but different expected
        # destinations.  The final point set is unchanged in the shuffled case.
        h5.create_dataset("mk", data=np.asarray([[0, 1, 0, 1], [0, 1, 0, 1]], dtype=np.int8))
        h5.create_dataset("mass", data=np.ones((2, 4), dtype=float))
        positions = np.zeros((2, 4, 3), dtype=float)
        positions[1] = [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                        [1.0, 0.1, 0.0], [0.0, 0.1, 0.0]]
        h5.create_dataset("position", data=positions)

    spec = {
        "lifecycle_model": "closed",
        "sources": {"mode": "mk"},
        "destination_frame": {"kind": "world"},
        "destinations": [{"name": "right", "type": "halfspace",
                           "normal": [1, 0, 0], "offset": 0.5, "side": "ge"}],
    }
    baseline = audit_transport(path, spec)
    # Rebuild only the final coordinates with the same set of points but swap
    # the two source identities' destinations.  A point-set metric would see
    # no change; source-conditioned transport must see the reversal.
    with h5py.File(path, "a") as h5:
        h5["position"][1] = h5["position"][1][[1, 0, 3, 2]]
    shuffled = audit_transport(path, spec)
    assert baseline["sources"]["0"]["mass_fraction"]["right"] == pytest.approx(1.0)
    assert baseline["sources"]["1"]["mass_fraction"]["right"] == pytest.approx(0.0)
    assert shuffled["sources"]["0"]["mass_fraction"]["right"] == pytest.approx(0.0)
    assert shuffled["sources"]["1"]["mass_fraction"]["right"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda spec: spec["destinations"][0].pop("side"), "side"),
        (lambda spec: spec["destinations"][0].update({"normal": [0, 0, 0]}), "non-zero"),
    ],
)
def test_transport_spec_rejects_ambiguous_or_invalid_halfspace_geometry(mutate, message):
    spec = {
        "lifecycle_model": "closed",
        "destination_frame": {"kind": "world"},
        "destinations": [{"name": "right", "type": "halfspace",
                           "normal": [1, 0, 0], "offset": 0.5, "side": "ge"}],
    }
    mutate(spec)
    with pytest.raises(ValueError, match=message):
        validate_transport_spec(spec)


def test_transport_spec_rejects_inverted_aabb():
    with pytest.raises(ValueError, match="max"):
        validate_transport_spec({
            "lifecycle_model": "closed",
            "destination_frame": {"kind": "world"},
            "destinations": [{"name": "inverted", "type": "aabb",
                               "min": [1, 0, 0], "max": [0, 0, 0]}],
        })


def test_transport_spec_accepts_all_declared_region_kinds():
    validate_transport_spec({
        "lifecycle_model": "open",
        "destination_frame": {"kind": "moving_affine", "world_from_frame_dataset": "control/frame"},
        "sources": {"mode": "regions", "frame": {"kind": "world"}, "regions": [
            {"name": "source", "type": "sphere", "center": [0, 0, 0], "radius": 0.25},
        ]},
        "destinations": [
            {"name": "box", "type": "aabb", "min": [-1, -1, -1], "max": [1, 1, 1]},
            {"name": "plane", "type": "halfspace", "normal": [1, 0, 0], "offset": 0, "side": "ge"},
        ],
    })
