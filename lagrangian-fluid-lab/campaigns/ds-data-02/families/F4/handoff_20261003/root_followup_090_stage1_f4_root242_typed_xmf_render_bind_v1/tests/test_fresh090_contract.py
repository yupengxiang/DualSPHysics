from pathlib import Path
import sys


WORKERS = Path(__file__).resolve().parents[1] / "workers"
sys.path.insert(0, str(WORKERS))

from preflight_fresh090_contract import check  # noqa: E402


def test_fresh090_contract():
    result = check()
    assert result == {
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "native_case_count": 6,
        "request_count": 18,
    }
