from scripts.r3_g2_f1_f3_matrix import records


def test_two_families_each_have_one_new_three_resolution_background():
    matrix = records()
    assert len(matrix) == 6
    for family in ("F1", "F3"):
        selected = [item for item in matrix if item["family"] == family]
        expected = {0.035, 0.024, 0.014} if family == "F1" else {0.035, 0.028, 0.022}
        assert {item["dp"] for item in selected} == expected
        assert len({item["background"] for item in selected}) == 1
        assert all(item["tout"] == 0.01 for item in selected)
    assert all(item["tmax"] == 1.5 for item in matrix if item["family"] == "F1")


def test_gpu_batches_do_not_repeat_gpu_in_first_batch():
    assert len({item["gpu"] for item in records()[:4]}) == 4
