import json

from scripts.l2_b2r_prepare import main


def test_prepare_cli_writes_nonterminal_waiting_contract(tmp_path, capsys):
    output = tmp_path / "b2r-preparation.json"
    assert main(["prepare", "--output", str(output)]) == 0
    payload = json.loads(output.read_text())
    stdout = json.loads(capsys.readouterr().out)
    assert payload["status"] == "waiting_for_R2"
    assert payload["launch_allowed"] is False
    assert stdout["waiting_for_R2"] is True
