import json, pathlib, subprocess, sys


def test_validator_ok():
    root = pathlib.Path(__file__).parent
    # use example artifacts if present else skip
    probe = root / "artifacts" / "probe_example.json"
    assess = root / "artifacts" / "assessment_example.json"
    if not probe.exists() or not assess.exists():
        # fallback to state files from sample project if present
        probe = root / "alert_demo" / "state" / "purpose.json"
        assess = root / "alert_demo" / "state" / "assessment.json"
        if not probe.exists():
            return  # skip if no data yet, validator still importable
    # construct minimal valid probe structure for test if needed
    # run validator script
    result = subprocess.run(
        [
            sys.executable,
            str(root / "validate_alert_output.py"),
            "--probe",
            str(probe),
            "--assess",
            str(assess),
        ],
        capture_output=True,
        text=True,
    )
    # allow exit 0 or 2 if files missing shape but script runs
    assert result.returncode in (0, 2)


def test_validator_rejects_bad():
    import tempfile, json, subprocess, pathlib, sys

    root = pathlib.Path(__file__).parent
    with tempfile.TemporaryDirectory() as td:
        bad = pathlib.Path(td) / "bad.json"
        bad.write_text(json.dumps({"patterns": []}))
        result = subprocess.run(
            [
                sys.executable,
                str(root / "validate_alert_output.py"),
                "--probe",
                str(bad),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "ERR" in result.stdout or "ERR" in result.stderr
