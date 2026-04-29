"""Regression test: confirm that a JSON file produced by SimulatorParameters.to_json
in the current installation can be re-loaded round-trip without errors.

After Phase 1A (migration to prosit-pm), this also confirms that the JSON
format is forward-compatible with the new package version.
"""

import json
import pm4py
from pm4py.objects.log.importer.xes import importer as xes_importer


def test_simulator_params_json_roundtrip(tmp_path, small_xes_path):
    from prosit.simulator import SimulatorParameters

    log = xes_importer.apply(str(small_xes_path))
    net, im, fm = pm4py.discover_petri_net_inductive(log, noise_threshold=0.2)

    params = SimulatorParameters(net, im, fm)
    params.discover_from_eventlog(log, max_depth_tree=0, verbose=False)

    out = tmp_path / "params.json"
    params.to_json(str(out))

    assert out.exists()
    raw = json.loads(out.read_text())
    assert "transition_params" in raw
    assert "resource_params" in raw
    assert "execution_time_params" in raw

    fresh = SimulatorParameters(net, im, fm)
    fresh.from_json(str(out))

    assert fresh.transition_weights
    assert fresh.resources
