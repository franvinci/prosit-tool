# Prosit: PROcess SImulation Tool

A Python Package for building and discovering Rule-Aware Business Process Simulation from event log data.


### How to use:

<ol>
    <li>
        <strong>Clone this repository.</strong>
    </li>
    <li>
        <strong>Create environment:</strong>
        <pre><code>$ conda env create -f environment.yml</code></pre>
    </li>
</ol>


```python
import sys
sys.path.append("src/")

import warnings
warnings.filterwarnings("ignore")

import pm4py
import pm4py.objects.log.importer.xes.importer as xes_importer

from prosit.simulator import SimulatorParameters, SimulatorEngine

# ----------------------------
# Step 1: Load Event Log
# ----------------------------
# Load the purchasing event log in XES format
log = xes_importer.apply("data/logs/purchasing.xes")

# ----------------------------
# Step 2: Discover Process Model
# ----------------------------
# Discover a Petri net from the event log using the Inductive Miner
net, im, fm = pm4py.discover_petri_net_inductive(log)

# ----------------------------
# Step 3: Initialize Simulation Parameters
# ----------------------------
# Initialize the simulation parameters with the discovered Petri net
params = SimulatorParameters(net, im, fm)

# ----------------------------
# Step 4: Discover Simulation Parameters from Event Log
# ----------------------------
# Automatically extract parameters from the event log
# - max_depth_tree: defines the depth of decision trees for rule discovery (higher = more complex rules). Default is 3.
#                   Use 0 to generate simple distributions without decision rules.
# - incremental_discovery: if True, gives more weight to recent traces. Default is False.
# - grace_period: used during incremental discovery to define the number of recent events to analyze (ignored if incremental_discovery=False). Default is 1000.
# - verbose: if True, prints discovery progress. Default is True.
params.discover_from_eventlog(log, max_depth_tree=2)

# ----------------------------
# Step 5: Save Parameters to JSON
# ----------------------------
# Save the discovered simulation parameters to a JSON file
params.to_json("simulation_params_purchasing.json")

# ----------------------------
# Step 6: Load Parameters
# ----------------------------
# Load simulation parameters from the saved JSON file
params = SimulatorParameters(net, im, fm)
params.from_json("simulation_params_purchasing.json")

# ----------------------------
# Step 7: Run Simulation
# ----------------------------
# Create a simulation engine with the loaded parameters
sim_engine = SimulatorEngine(params)

# Simulate a new event log
# - n_traces: number of traces (process instances) to simulate. Default is 1.
# - t_start: simulation start time. Default is the current datetime.
# - deterministic_time: if True, uses deterministic timing; otherwise, uses discovered stochastic distributions. Default is False.
# Returns a Pandas DataFrame representing the simulated event log
sim_log = sim_engine.apply(n_traces=100)
```
