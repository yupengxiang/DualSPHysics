import csv
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_handoff_20261002_recipe_v4.py"
SPEC = importlib.util.spec_from_file_location("f2_recipe_v4", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _xml(domain_low="-1.40,-1.20,-0.50", domain_high="3.00,1.20,2.20"):
    low = domain_low.split(",")
    high = domain_high.split(",")
    return f'''<case><execution><parameters>
      <parameter key="DtIni" value="0" />
      <parameter key="DtMin" value="0" />
      <parameter key="DtFixed" value="0" />
      <parameter key="TimeMax" value="4" />
      <parameter key="TimeOut" value="0.01" />
      <simulationdomain><posmin x="{low[0]}" y="{low[1]}" z="{low[2]}" />
        <posmax x="{high[0]}" y="{high[1]}" z="{high[2]}" /></simulationdomain>
    </parameters></execution></case>'''


def test_recipe_changes_only_registered_numeric_fields(tmp_path):
    old = tmp_path / "old.xml"
    new = tmp_path / "new.xml"
    old.write_text(_xml())
    rewritten = MODULE.replace_domain(old.read_text())
    rewritten = MODULE.replace_parameter(rewritten, "TimeOut", "0.001")
    new.write_text(rewritten)

    proof = MODULE.physical_equality(old, new)

    assert proof["physical_geometry_control_unchanged"] is True
    assert set(proof["differences"]) == {"TimeOut", "domain_low_m", "domain_high_m"}
    assert proof["new_numeric_fields"]["TimeOut"] == "0.001"
    assert proof["new_numeric_fields"]["domain_high_m"] == [3.2, 1.4, 2.4]


def test_half_native_dt_uses_observed_runparts_minimum(tmp_path):
    path = tmp_path / "RunPARTs.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["Part", "DtMin [s]"])
        writer.writerow(["0", "0"])
        writer.writerow(["1", "0.0002"])
        writer.writerow(["2", "0.00015"])

    minimum, evidence = MODULE.observed_min_dt(path)

    assert minimum == 0.00015
    assert evidence["positive_rows"] == 2
    assert MODULE.VARIANTS["half_native_dt"]["gpu_ready"] is False


def test_frozen_domain_repair_is_numerical_only():
    assert MODULE.DOMAIN_LOW == [-1.60, -1.40, -0.70]
    assert MODULE.DOMAIN_HIGH == [3.20, 1.40, 2.40]
    assert MODULE.OLD_DOMAIN_LOW == [-1.40, -1.20, -0.50]
    assert MODULE.OLD_DOMAIN_HIGH == [3.00, 1.20, 2.20]
    assert all(item["gpu_ready"] for name, item in MODULE.VARIANTS.items() if name == "baseline_save001")
    assert all(not item["gpu_ready"] for name, item in MODULE.VARIANTS.items() if name != "baseline_save001")
