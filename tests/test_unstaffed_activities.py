"""Activities of the model that nobody performs in the event log.

Since prosit-pm 1.0.5 such activities are simulated without a resource instead
of crashing the simulator. The tool has to (a) tell the user, and (b) cope with
empty resources everywhere the simulated log is consumed.
"""

import io
import json

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def pnml_with_unlogged_activity(tmp_path_factory):
    """Sequential net A -> B -> C -> D -> E. The tiny log stops at D."""
    import pm4py

    rows = []
    base = pd.Timestamp("2024-01-01 08:00", tz="UTC")
    for case in range(3):
        for ev, act in enumerate(["A", "B", "C", "D", "E"]):
            start = base + pd.Timedelta(hours=case * 3 + ev * 0.5)
            rows.append({
                "case:concept:name": f"m{case}",
                "concept:name": act,
                "org:resource": "r1",
                "start:timestamp": start,
                "time:timestamp": start + pd.Timedelta(minutes=10),
            })
    log = pm4py.convert_to_event_log(pd.DataFrame(rows))
    net, im, fm = pm4py.discover_petri_net_inductive(log)
    out = tmp_path_factory.mktemp("pnml_unlogged") / "with_e.pnml"
    pm4py.write_pnml(net, im, fm, str(out))
    return out


def _upload(client, xes_path, pnml_path):
    with open(xes_path, "rb") as fx, open(pnml_path, "rb") as fp:
        data = {
            "xes_file": (io.BytesIO(fx.read()), xes_path.name),
            "pnml_file": (io.BytesIO(fp.read()), pnml_path.name),
        }
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data
    return resp.get_json()["session_id"]


def test_unstaffed_activity_is_reported_and_simulated(client, tiny_xes_path, pnml_with_unlogged_activity):
    sid = _upload(client, tiny_xes_path, pnml_with_unlogged_activity)

    discover = client.post(f"/api/discover/{sid}")
    assert discover.status_code == 200, discover.data
    body = discover.get_json()
    assert body["success"] is True
    assert "E" in body["process_model"]["activities"]
    assert body["parameters"]["resource_params"]["act_to_resources"]["E"] == []

    # The user is told which activities run without a resource.
    assert len(body["warnings"]) == 1
    assert "without a resource" in body["warnings"][0]
    assert body["warnings"][0].rstrip().endswith("E")

    simulate = client.post(
        f"/api/simulate/{sid}",
        data=json.dumps({"num_instances": 6}),
        content_type="application/json",
    )
    assert simulate.status_code == 200, simulate.data
    sim_body = simulate.get_json()
    filename = sim_body["sim_output_filename"]

    csv = client.get(f"/api/download/{filename}")
    assert csv.status_code == 200
    df = pd.read_csv(io.BytesIO(csv.data))
    e_rows = df[df["concept:name"] == "E"]
    assert len(e_rows) == 6
    assert e_rows["org:resource"].isna().all()
    assert df.loc[df["concept:name"] != "E", "org:resource"].notna().all()

    # Everything that reads the simulated log copes with the empty resources.
    lists = client.get(f"/api/get_activities_and_resources/{sid}").get_json()
    assert "E" in lists["activities"]
    assert lists["resources"] == sorted(lists["resources"])
    assert all(isinstance(r, str) for r in lists["resources"])

    for viz, query in (
        ("process_map", ""),
        ("case_duration_dist", ""),
        ("resource_heatmap", ""),
        ("activity_duration_boxplot", "?activity=E"),
        ("waiting_time_dist", "?activity=E"),
    ):
        resp = client.get(f"/api/get_visualization/{sid}/{viz}{query}")
        assert resp.status_code == 200, (viz, resp.data)
        assert resp.get_json()["success"] is True

    xes = client.get(f"/api/download_xes/{filename}")
    assert xes.status_code == 200, xes.data
    assert b"<trace>" in xes.data
    # An event without a resource carries no org:resource attribute at all,
    # rather than a literal "nan".
    assert b'value="nan"' not in xes.data.lower()

    metrics = client.post(f"/api/metrics/{sid}")
    assert metrics.status_code == 200, metrics.data
    assert "resource-flow" in metrics.get_json()["prosit_metrics"]


def test_no_warning_when_every_activity_has_a_resource(client, tiny_xes_path):
    with open(tiny_xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), tiny_xes_path.name), "pnml_file": (io.BytesIO(b""), "")}
    sid = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()["session_id"]

    body = client.post(f"/api/discover/{sid}").get_json()
    assert body["success"] is True
    assert body["warnings"] == []
