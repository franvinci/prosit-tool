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
    assert body["prosit_metrics"], "expected non-empty prosit_metrics"


def test_discover_with_pnml(client, small_xes_path, small_pnml_path):
    """Regression test for BUG #1 (prosit_metrics undefined in PNML branch).

    Will fail until Phase 2 lands. Documenting it here makes the bug visible
    and turns the fix into a confirmable green checkmark.
    """
    upload = _upload_xes_and_pnml(client, small_xes_path, small_pnml_path).get_json()
    sid = upload["session_id"]

    resp = client.post(f"/api/discover/{sid}")
    assert resp.status_code == 200, resp.data


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
