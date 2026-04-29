"""Security-focused tests for the bug fixes in Phase 2."""

import pytest


def test_no_path_traversal_download(client):
    """BUG #5: download endpoint must reject relative paths escaping the folder."""
    # send_from_directory normalizes the path and refuses anything that resolves
    # outside the simulations folder. We expect a 4xx (404 in practice).
    resp = client.get("/api/download/..%2F..%2Fapp.py")
    assert resp.status_code in (400, 404)


def test_secret_key_required_in_prod(monkeypatch):
    """BUG #4: _resolve_secret_key must raise in production without SESSION_SECRET."""
    from app import _resolve_secret_key
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")

    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _resolve_secret_key()


def test_secret_key_generated_in_dev(monkeypatch):
    """In dev/testing the function returns a non-empty ephemeral key."""
    from app import _resolve_secret_key
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")
    key = _resolve_secret_key()
    assert isinstance(key, str) and len(key) >= 32


def test_concurrent_discover_no_state_leak(client, small_xes_path):
    """BUG #3: two sequential discoveries on different sessions must not share state."""
    import io

    def _upload():
        with open(small_xes_path, "rb") as f:
            data = {
                "xes_file": (io.BytesIO(f.read()), small_xes_path.name),
                "pnml_file": (io.BytesIO(b""), ""),
            }
        return client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()

    s1 = _upload()
    s2 = _upload()

    r1 = client.post(f"/api/discover/{s1['session_id']}").get_json()
    r2 = client.post(f"/api/discover/{s2['session_id']}").get_json()

    # Both must succeed and be self-consistent (no leak from session 1's run).
    assert r1["success"] and r2["success"]
    assert sorted(r1["process_model"]["activities"]) == sorted(r2["process_model"]["activities"])
    # Different json_filenames per session (different timestamps suffice).
    assert r1["json_filename"] != r2["json_filename"]


def test_upload_without_pnml_field(client, small_xes_path):
    """BUG #7: upload must succeed when pnml_file is omitted entirely."""
    import io

    with open(small_xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), small_xes_path.name)}
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data


def test_internal_error_does_not_leak_stack_trace(client, small_xes_path, tmp_path):
    """S1: 500 responses must not expose Traceback / paths / 'at 0x' to the client."""
    import io
    import os

    with open(small_xes_path, "rb") as f:
        data = {
            "xes_file": (io.BytesIO(f.read()), small_xes_path.name),
            "pnml_file": (io.BytesIO(b""), ""),
        }
    upload = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()
    sid = upload["session_id"]

    # Delete the uploaded XES from disk so the discovery view crashes when it
    # tries to load the event log. The file-existence check happens BEFORE
    # the load, so we need to bypass it: rename instead of delete to keep the
    # `os.path.exists` check happy and trigger the failure deeper in pm4py.
    from app import app as flask_app
    upload_folder = flask_app.config["UPLOAD_FOLDER"]
    xes_path = os.path.join(upload_folder, upload["filename"])
    # Truncate to a non-XES payload so xes_importer.apply raises.
    with open(xes_path, "wb") as f:
        f.write(b"not a valid xes file")

    resp = client.post(f"/api/discover/{sid}")
    assert resp.status_code == 500, resp.data

    body = resp.get_json()
    assert body["error"] == "Parameter discovery failed"
    assert "error_id" in body and len(body["error_id"]) >= 16

    # Critical: nothing internal should leak.
    raw = resp.data.decode("utf-8", errors="replace")
    assert "Traceback" not in raw
    assert " at 0x" not in raw
    assert upload_folder not in raw


def test_simulate_invalid_num_instances_returns_400(client, small_xes_path):
    """Phase 5: bad input now goes through the validator → 400, not 500."""
    import io
    import json

    with open(small_xes_path, "rb") as f:
        data = {
            "xes_file": (io.BytesIO(f.read()), small_xes_path.name),
            "pnml_file": (io.BytesIO(b""), ""),
        }
    upload = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()
    sid = upload["session_id"]
    client.post(f"/api/discover/{sid}")

    bad = client.post(
        f"/api/simulate/{sid}",
        data=json.dumps({"num_instances": 99999}),
        content_type="application/json",
    )
    assert bad.status_code == 400, bad.data

    not_an_int = client.post(
        f"/api/simulate/{sid}",
        data=json.dumps({"num_instances": "lots"}),
        content_type="application/json",
    )
    assert not_an_int.status_code == 400, not_an_int.data
