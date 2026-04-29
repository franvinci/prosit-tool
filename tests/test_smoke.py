"""End-to-end smoke tests for the upload → discover → simulate → download flow.

These tests use a real (but small) XES from example_data/. They are slow by
unit-test standards (~10-30s each) but cheap insurance against regressions
during the cleanup refactor.
"""

import io
import json


def _upload_xes(client, xes_path):
    with open(xes_path, "rb") as f:
        data = {
            "xes_file": (io.BytesIO(f.read()), xes_path.name),
            "pnml_file": (io.BytesIO(b""), ""),
        }
    return client.post("/api/upload", data=data, content_type="multipart/form-data")


def _upload_xes_and_pnml(client, xes_path, pnml_path):
    with open(xes_path, "rb") as fx, open(pnml_path, "rb") as fp:
        data = {
            "xes_file": (io.BytesIO(fx.read()), xes_path.name),
            "pnml_file": (io.BytesIO(fp.read()), pnml_path.name),
        }
    return client.post("/api/upload", data=data, content_type="multipart/form-data")


def test_upload_xes_creates_session(client, small_xes_path):
    resp = _upload_xes(client, small_xes_path)
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["success"] is True
    assert isinstance(body["session_id"], int)
    assert body["filename"].endswith(".xes")


def test_discover_xes_only(client, small_xes_path):
    upload = _upload_xes(client, small_xes_path).get_json()
    sid = upload["session_id"]

    resp = client.post(f"/api/discover/{sid}")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()

    assert body["success"] is True
    assert body["process_model"]["activities"], "expected non-empty activities"
    assert body["parameters"]["execution_time_params"]
    # Metrics are now computed via /api/metrics/<sid>; discover skips them.
    assert body.get("prosit_metrics") is not None
    assert body.get("prosit_metrics") == {}


def test_compute_metrics_endpoint_returns_metrics(client, tiny_xes_path):
    """The async metrics endpoint runs simulation+evaluate and stores the result.

    Uses a tiny synthetic log to keep the test under a few seconds — the
    expensive bits (r2gd, r3gd) scale with the number of traces and resources.
    """
    upload = _upload_xes(client, tiny_xes_path).get_json()
    sid = upload["session_id"]
    discover = client.post(f"/api/discover/{sid}")
    assert discover.status_code == 200, discover.data

    metrics_resp = client.post(f"/api/metrics/{sid}")
    assert metrics_resp.status_code == 200, metrics_resp.data
    body = metrics_resp.get_json()
    assert body["success"] is True
    metrics = body["prosit_metrics"]
    assert "control-flow" in metrics
    assert "time" in metrics
    assert "resource-flow" in metrics
    assert "generalization" in metrics

    # And the cached metrics are now persisted on the session.
    cached = client.get(f"/api/parameters/{sid}").get_json()
    assert cached["parameters"].get("prosit_metrics")


def test_discover_with_pnml(client, small_xes_path, small_pnml_path):
    """Regression test for BUG #1 (prosit_metrics undefined in PNML branch)."""
    upload = _upload_xes_and_pnml(client, small_xes_path, small_pnml_path).get_json()
    sid = upload["session_id"]

    resp = client.post(f"/api/discover/{sid}")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["success"] is True
    assert body["process_model"]["activities"], "expected non-empty activities"
    assert body.get("prosit_metrics") is not None


def test_export_parameters_returns_json_body(client, small_xes_path):
    """Regression for B2: export must stream JSON without leaking /tmp files."""
    upload = _upload_xes(client, small_xes_path).get_json()
    sid = upload["session_id"]

    discover = client.post(f"/api/discover/{sid}")
    assert discover.status_code == 200, discover.data

    resp = client.get(f"/api/export_parameters/{sid}")
    assert resp.status_code == 200, resp.data
    assert resp.mimetype == "application/json"
    body = json.loads(resp.data)
    assert isinstance(body, dict)
    assert body, "exported parameters JSON should not be empty"


def test_full_pipeline(client, small_xes_path):
    upload = _upload_xes(client, small_xes_path).get_json()
    sid = upload["session_id"]

    discover = client.post(f"/api/discover/{sid}")
    assert discover.status_code == 200, discover.data

    simulate = client.post(
        f"/api/simulate/{sid}",
        data=json.dumps({"num_instances": 10}),
        content_type="application/json",
    )
    assert simulate.status_code == 200, simulate.data
    sim_body = simulate.get_json()
    assert sim_body["num_events"] > 0
    out_filename = sim_body["sim_output_filename"]

    download = client.get(f"/api/download/{out_filename}")
    assert download.status_code == 200
    assert len(download.data) > 0


def test_discover_decision_tree_mode_with_data_attribute(client):
    """Regression for the 'str.get' crash on max_depth_tree>=1.

    prosit-pm 1.0.2 wraps distribution_data_attributes in {mode, data} and
    renames inner keys (dist_name→dist, min_value→min, ...). The previous
    converter iterated the wrapper and called .get() on the string 'distribution'.
    Uses synloan.xes because purchasing.xes has zero data attributes.
    """
    import io
    from pathlib import Path

    xes = Path(__file__).resolve().parent.parent / "example_data" / "synloan.xes"
    if not xes.exists():
        import pytest
        pytest.skip(f"missing fixture: {xes}")

    with open(xes, "rb") as f:
        data = {
            "xes_file": (io.BytesIO(f.read()), xes.name),
            "pnml_file": (io.BytesIO(b""), ""),
        }
    upload = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()
    sid = upload["session_id"]

    resp = client.post(f"/api/discover/{sid}?max_depth_tree=2")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["success"] is True
    # The synloan.xes log has at least one continuous attribute ('amount').
    da = body["parameters"]["data_attribute_params"]["distribution_data_attributes"]
    assert "amount" in da
    assert "distribution" in da["amount"]
