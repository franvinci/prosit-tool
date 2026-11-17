"""A failed parameter discovery must be reported, never papered over."""

import io

import pandas as pd

import prosit_integration
from evaluation import NO_RESOURCE_LABEL, compute_handover_error, compute_resource_ngd
from prosit_integration import describe_exception, unstaffed_activities


def _upload(client, xes_path):
    with open(xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), xes_path.name), "pnml_file": (io.BytesIO(b""), "")}
    return client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()["session_id"]


def test_failed_discovery_returns_error_instead_of_made_up_parameters(client, tiny_xes_path, monkeypatch):
    def boom(self, *args, **kwargs):
        raise KeyError("org:resource")

    monkeypatch.setattr(prosit_integration.SimulatorParameters, "discover_from_eventlog", boom)

    sid = _upload(client, tiny_xes_path)
    resp = client.post(f"/api/discover/{sid}")

    assert resp.status_code == 422, resp.data
    body = resp.get_json()
    assert "success" not in body
    assert "parameters" not in body
    assert body["error"].startswith("Parameter discovery failed.")
    assert "KeyError" in body["error"] and "org:resource" in body["error"]

    # Nothing usable was stored: there is no baseline to load or simulate.
    assert client.get(f"/api/parameters/{sid}").status_code == 404
    assert client.get(f"/api/sessions/{sid}/runs").get_json()["runs"] == []
    simulate = client.post(f"/api/simulate/{sid}", json={"num_instances": 2})
    assert simulate.status_code == 400

    from models import SimulationSession
    from app import db
    assert db.session.get(SimulationSession, sid).status == "error"


def test_discovery_can_be_retried_after_a_failure(client, tiny_xes_path, monkeypatch):
    sid = _upload(client, tiny_xes_path)

    with monkeypatch.context() as patch:
        patch.setattr(
            prosit_integration.SimulatorParameters, "discover_from_eventlog",
            lambda self, *a, **k: (_ for _ in ()).throw(ValueError("empty log")),
        )
        assert client.post(f"/api/discover/{sid}").status_code == 422

    retry = client.post(f"/api/discover/{sid}")
    assert retry.status_code == 200, retry.data
    assert retry.get_json()["success"] is True


def test_describe_exception_keeps_the_cause_and_drops_internals():
    exc = ValueError("could not read /home/someone/project/uploads/1_log.xes (object at 0x7f3a2c1b9d30)")
    text = describe_exception(exc)
    assert text.startswith("ValueError: could not read")
    assert "/home/someone" not in text and "<path>" in text
    assert "0x7f3a" not in text and "<address>" in text

    assert describe_exception(KeyError("start:timestamp")) == "KeyError: 'start:timestamp'"
    assert describe_exception(RuntimeError()) == "RuntimeError"

    long = describe_exception(ValueError("x" * 1000))
    assert len(long) <= len("ValueError: ") + 300 and long.endswith("…")


def test_describe_exception_handles_windows_paths():
    text = describe_exception(OSError(r"cannot open C:\Users\someone\AppData\prosit\log.xes"))
    assert "someone" not in text and "<path>" in text


def test_unstaffed_activities_lists_only_activities_without_resources():
    params = {"resource_params": {"act_to_resources": {"B": ["r1"], "Z": [], "A": []}}}
    assert unstaffed_activities(params) == ["A", "Z"]
    assert unstaffed_activities({"resource_params": {"act_to_resources": {"B": ["r1"]}}}) == []
    assert unstaffed_activities({}) == []
    assert unstaffed_activities(None) == []


def _log(resources_per_case):
    rows = []
    base = pd.Timestamp("2024-01-01 08:00", tz="UTC")
    for case, resources in enumerate(resources_per_case):
        for ev, res in enumerate(resources):
            start = base + pd.Timedelta(hours=case, minutes=ev * 20)
            rows.append({
                "case:concept:name": f"c{case}",
                "concept:name": f"act{ev}",
                "org:resource": res,
                "start:timestamp": start,
                "time:timestamp": start + pd.Timedelta(minutes=10),
            })
    return pd.DataFrame(rows)


def test_resource_metrics_treat_missing_resources_as_one_label():
    with_gaps = _log([["r1", None, "r2"], ["r1", float("nan"), "r2"]])
    labelled = _log([["r1", NO_RESOURCE_LABEL, "r2"], ["r1", NO_RESOURCE_LABEL, "r2"]])

    # Two logs that differ only in how "no resource" is spelled are identical.
    assert compute_resource_ngd(with_gaps, labelled, n=2) == 0
    assert compute_handover_error(with_gaps, labelled) == 0
    # ...and the inputs are left as they were.
    assert with_gaps["org:resource"].isna().sum() == 2

    different = _log([["r1", "r1", "r2"], ["r1", "r1", "r2"]])
    assert compute_resource_ngd(with_gaps, different, n=2) > 0
    assert compute_handover_error(with_gaps, different) > 0
