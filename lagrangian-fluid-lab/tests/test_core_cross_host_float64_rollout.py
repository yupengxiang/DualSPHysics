import h5py
import numpy as np

from scripts import core_cross_host_float64_rollout as rollout

from test_core_contract import example_state


def test_full_rollout_parser_is_fixed_to_registered_835_transitions():
    args = rollout.build_parser().parse_args([
        "--bundle-root", "/bundle", "--case-id", "fixture", "--output", "/receipt.json",
    ])
    assert args.maximum_steps == 835
    assert args.chunk_size == 256
    assert args.model_kind == "graph_residual"


def test_streaming_h5_writer_preserves_native_state_and_identity_axes(tmp_path):
    initial = example_state()
    path = tmp_path / "rollout.h5"
    handle = rollout._open_trajectory(
        path, times=np.array([0.0, .01, .02]), initial=initial, total_steps=2)
    following = initial
    following_position = initial.position + .001
    following_velocity = initial.velocity + .002
    handle["position"][1] = following_position
    handle["velocity"][1] = following_velocity
    handle["valid"][1] = initial.valid
    handle.close()

    with h5py.File(path, "r") as archive:
        assert archive.attrs["schema"] == rollout.SCHEMA
        assert archive.attrs["storage_dtype"] == "float64"
        assert bool(archive.attrs["future_state_inputs"]) is False
        assert archive["position"].shape == (3, 2, 3)
        assert archive["velocity"].dtype == np.float64
        assert np.array_equal(archive["particle_id"][:], initial.particle_id)
        assert np.allclose(archive["position"][1], following_position)
        assert np.allclose(archive["velocity"][1], following_velocity)


def test_characteristic_scales_use_frozen_known_inputs_geometry_contract():
    from test_core_contract import example_known
    from types import SimpleNamespace
    current = example_known()
    known = SimpleNamespace(geometry=current.geometry, numerics=current.numerics, physics=current.physics)
    assert not hasattr(known, 'geometry_at')
    length, speed = rollout._characteristic_scales(known)
    assert length == 2.0
    assert np.isclose(speed, np.sqrt(9.81 * length))
