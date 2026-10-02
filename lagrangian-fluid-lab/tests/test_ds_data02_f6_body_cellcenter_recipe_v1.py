from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from ds_data02_f6_body_cellcenter_recipe_v1 import (  # noqa: E402
    RecipeError,
    centered_box_recipe,
    integer_cell_counts,
    native_matches_target,
)


LOW = [2.0, 0.8, 0.88]
SIZE = [0.8, 0.8, 0.4]


@pytest.mark.parametrize(
    ("dp", "counts", "first", "last"),
    [
        (0.025, [32, 32, 16], [2.0125, 0.8125, 0.8925], [2.7875, 1.5875, 1.2675]),
        (0.02, [40, 40, 20], [2.01, 0.81, 0.89], [2.79, 1.59, 1.27]),
        (0.0125, [64, 64, 32], [2.00625, 0.80625, 0.88625], [2.79375, 1.59375, 1.27375]),
    ],
)
def test_recipe_has_interior_cell_centres_and_exact_count(
    dp: float, counts: list[int], first: list[float], last: list[float]
) -> None:
    recipe = centered_box_recipe(LOW, SIZE, dp)
    assert recipe["cell_counts_xyz"] == counts
    assert recipe["ideal_type2_count"] == counts[0] * counts[1] * counts[2]
    assert recipe["ideal_first_center_m"] == pytest.approx(first)
    assert recipe["ideal_last_center_m"] == pytest.approx(last)
    assert recipe["ideal_centroid_m"] == pytest.approx([2.4, 1.2, 1.08])
    assert recipe["proxy_count_times_dp_cubed_m3"] == pytest.approx(0.256)
    for value, low, high in zip(
        recipe["ideal_first_center_m"], LOW, [low + size for low, size in zip(LOW, SIZE)]
    ):
        assert low < value < high
    for value, low, high in zip(
        recipe["ideal_last_center_m"], LOW, [low + size for low, size in zip(LOW, SIZE)]
    ):
        assert low < value < high


def test_non_commensurate_body_is_rejected() -> None:
    with pytest.raises(RecipeError, match="integer multiple"):
        integer_cell_counts([0.81, 0.8, 0.4], 0.025)


@pytest.mark.parametrize(
    ("dp", "count", "point_min", "point_max", "centroid"),
    [
        (0.025, 18513, [2.0, 0.8000000119, 0.875], [2.79999995, 1.60000002, 1.27499998], [2.4, 1.2, 1.075]),
        (0.02, 35301, [2.00999999, 0.81000000, 0.88999999], [2.80999994, 1.61000001, 1.28999996], [2.41, 1.21, 1.09]),
        (0.0125, 139425, [1.99374998, 0.80624998, 0.88125002], [2.79375005, 1.60625005, 1.28125], [2.39375, 1.20625, 1.08125]),
    ],
)
def test_existing_native_rows_are_not_promoted_to_target(
    dp: float,
    count: int,
    point_min: list[float],
    point_max: list[float],
    centroid: list[float],
) -> None:
    target = centered_box_recipe(LOW, SIZE, dp)
    native = {
        "type2_count": count,
        "point_min_m": point_min,
        "point_max_m": point_max,
        "point_centroid_m": centroid,
    }
    assert native_matches_target(native, target) is False
