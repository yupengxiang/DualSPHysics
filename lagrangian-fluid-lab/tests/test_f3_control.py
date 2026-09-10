import numpy as np
import pytest
from scripts.f3_control import AccelerationControl


def test_zero_drive_preserves_gravity():
    c=AccelerationControl([[0,0,0,-9.81,0,0,0],[1,0,0,-9.81,0,0,0]])
    np.testing.assert_allclose(c.body_acceleration(.5,[[.1,0,.1]],[[0,0,0]]),[[0,0,-9.81]])
    with pytest.raises(ValueError,match='coverage'):c.at(1.1)


def test_constant_angular_acceleration_at_origin_and_initial_zero_omega():
    c=AccelerationControl([[0,0,0,0,0,2,0],[1,0,0,0,0,2,0]])
    # At t=0 alpha_y=2, r_z=1 -> a_x=2; zero integrated angular speed.
    np.testing.assert_allclose(c.body_acceleration(0,[[.45,0,1]],[[0,0,0]]),[[2,0,0]])
    # At t=1 omega_y=2 -> centripetal a_z=-4 in addition to a_x=2.
    np.testing.assert_allclose(c.body_acceleration(1,[[.45,0,1]],[[0,0,0]]),[[2,0,-4]])


def test_future_control_tail_cannot_change_current_input():
    a=np.array([[0,1,0,-9.81,0,2,0],[.1,2,0,-9.81,0,3,0],[.2,3,0,-9.81,0,4,0],[.3,4,0,-9.81,0,5,0]])
    b=a.copy();b[3,1:]=1e5
    c,d=AccelerationControl(a),AccelerationControl(b)
    for t in (0,.05,.1,.15,.2):
        np.testing.assert_array_equal(np.array(c.at(t)),np.array(d.at(t)))
