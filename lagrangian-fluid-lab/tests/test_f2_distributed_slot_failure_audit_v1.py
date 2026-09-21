from __future__ import annotations

import numpy as np

from scripts.f2_distributed_slot_failure_audit_v1 import summarize


def test_partition_summary_separates_outer_and_gate_zero_normals():
    points = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]], dtype=float)
    mk = np.array([17, 17, 18, 18])
    normal = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0]], dtype=float)
    sizes = np.linalg.norm(normal, axis=1)
    result = summarize(points, mk, normal, sizes)
    assert result["zero_boundnor_count"] == 2
    assert [row["zero_boundnor_count"] for row in result["mk_partitions"]] == [1, 1]
    assert result["arrays_finite"] is True
