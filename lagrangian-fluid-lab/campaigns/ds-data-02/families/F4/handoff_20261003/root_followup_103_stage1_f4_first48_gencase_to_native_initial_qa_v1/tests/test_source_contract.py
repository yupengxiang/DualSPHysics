from pathlib import Path
import runpy

def test_fresh103_source_contract():
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "workers" / "validate_fresh103_source.py"), run_name="__main__")
