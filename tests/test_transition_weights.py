"""Transition weights must survive the edit -> save -> reload -> simulate loop.

Weights are keyed by the Petri net transition *name*. Without rules they are
plain numbers; in rules mode a weight can also be a decision tree.
"""

import io

import pytest


def _upload_and_discover(client, xes_path, query=""):
    with open(xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), xes_path.name), "pnml_file": (io.BytesIO(b""), "")}
    sid = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()["session_id"]
    resp = client.post(f"/api/discover/{sid}{query}")
    assert resp.status_code == 200, resp.data
    return sid, resp.get_json()["parameters"]


def _create_run(client, sid, name, parameters):
    resp = client.post(f"/api/sessions/{sid}/runs", json={"name": name, "parameters": parameters})
    assert resp.status_code == 200, resp.data
    return resp.get_json()["run"]["id"]


def _weights(parameters):
    return parameters["transition_params"]["transition_weights"]


def test_weights_are_keyed_by_transition_name(client, tiny_xes_path):
    _, params = _upload_and_discover(client, tiny_xes_path)
    assert set(_weights(params)) == set(params["process_model"]["transitions"])
    assert all(isinstance(w, (int, float)) for w in _weights(params).values())


def test_numeric_weight_edit_survives_save_reload_and_simulation(client, tiny_xes_path):
    sid, params = _upload_and_discover(client, tiny_xes_path)
    name = sorted(_weights(params))[0]
    original = _weights(params)[name]
    assert original != pytest.approx(0.123)

    _weights(params)[name] = 0.123
    run_id = _create_run(client, sid, "Edited weight", params)

    reloaded = client.get(f"/api/runs/{run_id}").get_json()["parameters"]
    assert _weights(reloaded)[name] == pytest.approx(0.123)
    # Every other weight is untouched.
    for other, value in _weights(params).items():
        if other != name:
            assert _weights(reloaded)[other] == pytest.approx(value)

    # The baseline keeps the discovered value.
    baseline = client.get(f"/api/parameters/{sid}").get_json()["parameters"]
    assert _weights(baseline)[name] == pytest.approx(original)

    simulate = client.post(f"/api/runs/{run_id}/simulate", json={"num_instances": 4})
    assert simulate.status_code == 200, simulate.data
    assert simulate.get_json()["num_events"] > 0


def test_zero_weight_is_kept_as_zero(client, tiny_xes_path):
    """A weight of 0 is a legitimate value, not "missing"."""
    sid, params = _upload_and_discover(client, tiny_xes_path)
    name = sorted(_weights(params))[-1]
    _weights(params)[name] = 0

    run_id = _create_run(client, sid, "Zero weight", params)
    reloaded = client.get(f"/api/runs/{run_id}").get_json()["parameters"]
    assert name in _weights(reloaded)
    assert _weights(reloaded)[name] == 0

    simulate = client.post(f"/api/runs/{run_id}/simulate", json={"num_instances": 3})
    assert simulate.status_code == 200, simulate.data


def test_update_existing_run_replaces_weight(client, tiny_xes_path):
    sid, params = _upload_and_discover(client, tiny_xes_path)
    name = sorted(_weights(params))[0]
    run_id = _create_run(client, sid, "Scenario", params)

    _weights(params)[name] = 0.42
    update = client.put(f"/api/runs/{run_id}", json={"parameters": params})
    assert update.status_code == 200, update.data

    reloaded = client.get(f"/api/runs/{run_id}").get_json()["parameters"]
    assert _weights(reloaded)[name] == pytest.approx(0.42)


def _normalise_tree(tree):
    """Compare trees regardless of how JSON spelled the branch keys.

    prosit-pm writes the branches as ``true``/``false`` when the tree is fresh
    in memory and as ``1``/``0`` after a JSON round trip; both mean the same.
    """
    truthy = {"true": True, "1": True, "True": True, "false": False, "0": False, "False": False}
    out = {}
    for node_id, node in tree.items():
        node = dict(node)
        if "children" in node:
            node["children"] = {truthy[str(k)]: int(v) for k, v in node["children"].items()}
        out[str(node_id)] = node
    return out


def test_decision_tree_weight_survives_save_reload_and_simulation(client, tiny_xes_path):
    sid, params = _upload_and_discover(client, tiny_xes_path, "?max_depth_tree=1")
    name = sorted(_weights(params))[0]

    # "A" counts how many times the case went through activity A: a feature
    # the simulator always provides.
    tree = {
        "0": {"feature": "A", "threshold": 0.5, "children": {"true": 1, "false": 2}},
        "1": {"value": 0.25},
        "2": {"value": 0.75},
    }
    _weights(params)[name] = tree
    run_id = _create_run(client, sid, "Rule on a transition", params)

    reloaded = client.get(f"/api/runs/{run_id}").get_json()["parameters"]
    assert _normalise_tree(_weights(reloaded)[name]) == _normalise_tree(tree)

    simulate = client.post(f"/api/runs/{run_id}/simulate", json={"num_instances": 4})
    assert simulate.status_code == 200, simulate.data
    assert simulate.get_json()["num_events"] > 0
