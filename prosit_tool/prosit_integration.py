import logging
import re
from collections import Counter
from datetime import datetime

import pandas as pd
import pm4py
from pm4py.algo.evaluation.replay_fitness import algorithm as fitness_evaluator
from pm4py.algo.evaluation.precision import algorithm as precision_evaluator

from prosit.simulator import SimulatorParameters, SimulatorEngine
from . import workers
from .evaluation import evaluate, compute_log_kpis, compute_log_charts
from .format_converters import attribute_entry_from_prosit, prosit_entry_to_app
from .petri_dot import petri_net_to_dot
from .progress import Bar, Step

logger = logging.getLogger(__name__)

# What ``discover_from_eventlog(verbose=True)`` prints when it begins a step
# (prosit-pm 1.0.5), and the step of the plan below that it stands for.
LIBRARY_STEPS = {
    'Resources discovery...': 'resources',
    'Data attributes discovery...': 'attributes',
    'Feature discovery...': 'features',
    'Transition Probabilities discovery...': 'transitions',
    'Incremental Transition Probabilities discovery...': 'transitions',
    'Resource Weights discovery...': 'resource_weights',
    'Incremental Resource Weights discovery...': 'resource_weights',
    'Calendars discovery...': 'calendars',
    'Execution Time discovery...': 'execution_times',
    'Incremental Execution Time discovery...': 'execution_times',
    'Waiting Time discovery...': 'waiting_times',
    'Incremental Waiting Time discovery...': 'waiting_times',
    'Model fitting...': 'fitting',
    'Arrival Time discovery...': 'arrival_times',
    'Incremental Arrival Time discovery...': 'arrival_times',
}


def discovery_steps(*, importing_model=False, rules=False, incremental=False):
    """The steps of a discovery, in the order in which they run.

    The weight of a step is the share of the time it usually takes, measured
    on the example logs. "Usually" is the word: the three steps that align the
    log with the model (fitness, precision, replay) take nearly all the time
    on a log with thousands of variants and next to none on one with a dozen.
    The steps with a progress bar of their own move within their share.
    """
    models = (Bar(unit='models'),)
    steps = [
        Step('log', 'Reading the event log', 5, (Bar(unit='traces'),)),
        Step('model', 'Reading the Petri net' if importing_model else 'Discovering the process model', 1),
        Step('fitness', 'Measuring the fitness of the model', 24, (Bar(unit='variants'),)),
        Step('precision', 'Measuring the precision of the model', 26, (Bar(unit='variants'),)),
        Step('resources', 'Discovering the resources', 1),
        Step('attributes', 'Discovering the data attributes', 1),
        # Aligning every variant with the model, then one pass over the traces.
        Step('features', 'Replaying the log on the model', 22, (Bar(0.85, 'variants'), Bar(0.15, 'traces'))),
    ]
    if incremental:
        # Every step fits its own models, one after the other.
        steps += [
            Step('transitions', 'Discovering the transition weights', 6, models),
            Step('resource_weights', 'Discovering the resource weights', 9, models),
            Step('calendars', 'Discovering the calendars', 1),
            Step('execution_times', 'Discovering the execution times', 2, models),
            Step('waiting_times', 'Discovering the waiting times', 2, models),
        ]
    else:
        # Every step only prepares its models: they are all fitted together.
        steps += [
            Step('transitions', 'Discovering the transition weights', 2),
            Step('resource_weights', 'Discovering the resource weights', 1),
            Step('calendars', 'Discovering the calendars', 1),
            Step('execution_times', 'Discovering the execution times', 1),
            Step('waiting_times', 'Discovering the waiting times', 1),
            Step('fitting', 'Fitting the models', 16 if rules else 10, models),
        ]
    steps += [
        Step('arrival_times', 'Discovering the arrival times', 1),
        Step('saving', 'Saving the parameters', 2),
    ]
    return steps


class DiscoveryError(Exception):
    """Parameter discovery failed; the message is safe to show to the user."""


class ModelMismatchError(DiscoveryError):
    """The Petri net and the event log do not describe the same process."""


def listed(names, limit=8):
    """Names for a message: the first few, then how many more there are."""
    names = [str(name) for name in names]
    if not names:
        return '(none)'
    shown = ', '.join(names[:limit])
    return shown if len(names) <= limit else f'{shown} and {len(names) - limit} more'


def activities_outside_model(event_log, net):
    """``(activities of the net, events per activity of the log, the same for the activities the net lacks)``.

    prosit-pm learns from the events it can replay on the net. An event whose
    activity is not the label of any transition cannot be replayed: it is left
    out of everything that is learnt, and nothing like it is ever simulated.
    """
    labels = {transition.label for transition in net.transitions if transition.label is not None}
    events = Counter(event['concept:name'] for trace in event_log for event in trace)
    return labels, events, {activity: count for activity, count in events.items() if activity not in labels}


_PATH_RE = re.compile(r'(?:[A-Za-z]:)?(?:[\\/][^\\/\s:\'"]+){2,}')
_ADDRESS_RE = re.compile(r'0x[0-9a-fA-F]+')


def describe_exception(exc, limit=300):
    """One-line, user-facing description of an exception.

    Keeps the exception type and message (the part that tells the user what is
    wrong with their log) and drops what does not belong in an HTTP response:
    file-system paths, memory addresses and anything past ``limit`` characters.
    """
    text = ' '.join(str(exc).split())
    text = _PATH_RE.sub('<path>', text)
    text = _ADDRESS_RE.sub('<address>', text)
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    name = type(exc).__name__
    return f'{name}: {text}' if text else name


def unstaffed_activities(prosit_params):
    """Activities of the model that no resource can perform.

    prosit-pm simulates them without a resource (and without a calendar), which
    is worth telling the user because it usually means the model contains an
    activity that never occurs in the log.
    """
    act_to_resources = (prosit_params or {}).get('resource_params', {}).get('act_to_resources', {})
    return sorted(str(act) for act, resources in act_to_resources.items() if not resources)


class ProSiTIntegration:
    """Integration layer for ProSiT library functionality.
    
    This class provides methods to discover process models, extract parameters,
    and run simulations using the ProSiT framework.
    """
    
    def __init__(self, progress=None):
        self.process_model = None
        self.event_log = None
        self.prosit_params = None
        self.prosit_metrics = None
        self.discovery_warnings = []
        # What the user should know about the model with respect to the log.
        self.model_warnings = []
        # Whoever follows the discovery (``prosit_tool.progress.Progress``), if anyone.
        self._progress = progress

    def _begin(self, step):
        """A step of ``discovery_steps`` begins."""
        if self._progress is not None:
            self._progress.start(step)

    def _check_model_against_log(self, net):
        """Refuse a net that has no activity of the log; note the activities it lacks.

        It costs one pass over the events, and comes before the minutes that
        measuring fitness and precision can take.
        """
        self.model_warnings = []
        if self.event_log is None:
            return
        labels, events, outside = activities_outside_model(self.event_log, net)
        if len(outside) == len(events):
            raise ModelMismatchError(
                'None of the activities of the event log is in the Petri net, so the log cannot be replayed on it. '
                f'Activities of the log: {listed(sorted(events, key=str))}. '
                f'Activities of the net: {listed(sorted(labels, key=str))}. '
                'The names have to be identical: check that the PNML file is the model of this log.'
            )
        if outside:
            by_size = sorted(outside.items(), key=lambda item: (-item[1], str(item[0])))
            self.model_warnings.append(
                'These activities of the event log are not in the process model, so their events are left out '
                'of what is learnt and nothing like them is simulated: '
                + listed([f'{activity} ({count} event{"" if count == 1 else "s"})' for activity, count in by_size], 10)
                + '.'
            )

    def discover_process_model(self, noise_threshold=0.2):
        """Discover process model using PM4Py inductive miner.
        
        Args:
            noise_threshold: Noise threshold for the inductive miner algorithm
            
        Updates:
            self.process_model: Dictionary containing process model data
        """
        try:
            logger.info(f"Discovering process model via Inductive Miner with noise threshold {noise_threshold}")
            
            # Apply inductive miner to discover Petri net
            self._begin('model')
            net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(self.event_log, noise_threshold=noise_threshold)
            # The miner leaves out what it takes for noise: say which activities.
            self._check_model_against_log(net)

            self._begin('fitness')
            fitness = fitness_evaluator.apply(self.event_log, net, initial_marking, final_marking)['averageFitness']
            self._begin('precision')
            precision = precision_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            self.process_model = self._describe_process_model(net, initial_marking, final_marking, fitness, precision)

            logger.info("Discovered process model with %d activities", len(self.process_model['activities']))
            
        except Exception as e:
            logger.error(f"Error discovering process model: {str(e)}")
            raise
    
    def import_petri_net_from_pnml(self, pnml_file_path, compute_metrics=True):
        """Import Petri net structure from PNML file.

        Args:
            pnml_file_path: Path to the PNML file containing the Petri net.
            compute_metrics: If True, compute fitness/precision against
                ``self.event_log``. If False (or no event log set), populate
                metrics with zeros — useful when the only goal is to reload the
                net for a later simulation.

        Updates:
            self.process_model: Dictionary containing the imported process model.
        """
        try:
            logger.info(f"Importing Petri net structure from {pnml_file_path}")
            self._begin('model')
            net, initial_marking, final_marking = pm4py.read_pnml(pnml_file_path)
            self._check_model_against_log(net)

            if compute_metrics and self.event_log is not None:
                self._begin('fitness')
                fitness = fitness_evaluator.apply(self.event_log, net, initial_marking, final_marking)['averageFitness']
                self._begin('precision')
                precision = precision_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            else:
                fitness = precision = 0.0
            self.process_model = self._describe_process_model(net, initial_marking, final_marking, fitness, precision)

            logger.info(
                "PNML Petri net imported successfully: %d activities, %d places",
                len(self.process_model['activities']), len(self.process_model['places']),
            )

        except Exception as e:
            logger.error(f"Failed to import Petri net from PNML: {str(e)}")
            raise

    @staticmethod
    def _describe_process_model(net, initial_marking, final_marking, fitness, precision):
        """What the rest of the tool needs to know about a net.

        ``dot`` is the description the page draws, ``nodes`` says which
        transition or place each node of the drawing is (see ``petri_dot``).
        """
        dot, nodes = petri_net_to_dot(net, initial_marking, final_marking)
        transitions = [node for node in nodes.values() if node['type'] == 'transition']
        return {
            # Labels of the visible transitions; a label used by more than one
            # transition is listed once.
            'activities': list(dict.fromkeys(t['label'] for t in transitions if not t['silent'])),
            'transitions': [t['name'] for t in transitions],
            'places': [node['name'] for node in nodes.values() if node['type'] == 'place'],
            'transition_label_map': {t['name']: t['label'] or t['name'] for t in transitions},
            'silent_transitions': [t['name'] for t in transitions if t['silent']],
            'fitness': fitness,
            'precision': precision,
            'f_measure': 2 * fitness * precision / (fitness + precision) if (fitness + precision) else 0.0,
            'dot': dot,
            'nodes': nodes,
            'net': net,
            'initial_marking': initial_marking,
            'final_marking': final_marking,
        }

    def discover_parameters(
        self,
        max_depth_tree=0,
        incremental_discovery=False,
        grace_period=1000,
        enable_multitasking=False,
        multitasking_thr=0.05,
        random_state=72,
        use_workload_features=False,
        attribute_mode='distribution',
        compute_metrics=False,
    ):
        """
        Discover simulation parameters using ProSiT library.

        Args:
            max_depth_tree: Maximum depth for decision trees (0 disables rules mode)
            incremental_discovery: Whether to use incremental learning algorithms
            grace_period: Number of events to wait before starting incremental learning
            enable_multitasking: Whether to discover per-resource multitasking
            multitasking_thr: Threshold for detecting multitasking resources
            random_state: Seed for reproducibility
            use_workload_features: Whether to engineer workload features
            attribute_mode: Modeling mode for data attributes (e.g. 'distribution')
            compute_metrics: Also run the reference simulation and evaluate it

        Raises:
            DiscoveryError: prosit-pm could not discover parameters from the log.
                Non-fatal findings are collected in ``self.discovery_warnings``.

        Returns:
            Dictionary containing discovered parameters in application format
        """
        try:
            logger.info("Discovering parameters from Event Log")

            if not self.process_model:
                self.discover_process_model()

            # Get the process model components
            net = self.process_model['net']
            initial_marking = self.process_model['initial_marking']
            final_marking = self.process_model['final_marking']

            # Create ProSiT parameters instance
            self.prosit_params = SimulatorParameters(net, initial_marking, final_marking)

            # Discover parameters from event log (max_depth_tree=0 disables rules mode)
            logger.info("Starting ProSiT parameter discovery...")
            self.discovery_warnings = []
            try:
                # The models are fitted on several processes: in an executable
                # they have to be started in a way of their own (see workers).
                with workers.joblib_on_worker_processes():
                    self.prosit_params.discover_from_eventlog(
                        self.event_log,
                        max_depth_tree=max_depth_tree,
                        incremental_discovery=incremental_discovery,
                        grace_period=grace_period,
                        enable_multitasking=enable_multitasking,
                        multitasking_thr=multitasking_thr,
                        random_state=random_state,
                        use_workload_features=use_workload_features,
                        attribute_mode=attribute_mode,
                        # It prints the name of each step it begins: that is how
                        # the progress shown to the user follows it (LIBRARY_STEPS).
                        verbose=True,
                    )
                self.prosit_params = self.prosit_params.to_dict()
            except Exception as discovery_error:
                # Never substitute made-up parameters for a failed discovery:
                # the user would simulate a model that has nothing to do with
                # their log. Report what went wrong instead.
                self.prosit_params = None
                logger.exception("ProSiT discover_from_eventlog failed")
                reason = describe_exception(discovery_error)
                if self.model_warnings:
                    # The likeliest lead when the library gives up on a log.
                    reason += ' — ' + self.model_warnings[0]
                raise DiscoveryError(reason) from discovery_error
            logger.info("ProSiT parameter discovery completed successfully")

            unstarted = workers.problem(check=False)
            if unstarted:
                # The whole reason, paths included, is in what the program writes as it runs.
                self.discovery_warnings.append(
                    'The models were fitted by one process, which takes longer: the program could not '
                    f'start its worker processes ({_PATH_RE.sub("<path>", unstarted)}).'
                )

            unstaffed = unstaffed_activities(self.prosit_params)
            if unstaffed:
                self.discovery_warnings.append(
                    "No resource performs these activities in the event log, so they are "
                    "simulated without a resource: " + ", ".join(unstaffed)
                )

            if compute_metrics:
                self.compute_prosit_metrics()
            else:
                self.prosit_metrics = {}

            return self._convert_prosit_to_app_format()

        except DiscoveryError:
            raise
        except Exception as e:
            logger.error(f"Error discovering parameters: {str(e)}")
            raise

    def compute_prosit_metrics(self):
        """Run a simulation matched to the original event log and evaluate metrics.

        Requires ``self.event_log`` and ``self.prosit_params`` to be set.
        Stores and returns ``self.prosit_metrics`` grouped by category.
        """
        if self.event_log is None:
            raise ValueError("event_log is not loaded; cannot evaluate metrics")
        if not self.prosit_params:
            raise ValueError("prosit_params not loaded; cannot evaluate metrics")

        df_event_log = pm4py.convert_to_dataframe(self.event_log)
        df_event_log['case:concept:name'] = df_event_log['case:concept:name'].astype(str)
        df_event_log['time:timestamp'] = pd.to_datetime(df_event_log['time:timestamp'])
        df_event_log['start:timestamp'] = pd.to_datetime(df_event_log['start:timestamp'])
        df_event_log.sort_values(by=['start:timestamp', 'time:timestamp'], inplace=True)
        df_event_log.reset_index(drop=True, inplace=True)
        start_t = df_event_log.iloc[0]['start:timestamp']

        simulated_event_log = self.run_simulation(n_traces=len(self.event_log), start_timestamp=start_t)
        logger.info("Simulation for metrics completed")
        metrics = evaluate(
            df_event_log,
            simulated_event_log,
            metrics_labels=['2gd', '3gd', 'ctd', 'car', 'r2gd', 'r3gd', 'ctd_entropy', 'etd_entropy'],
        )
        self.prosit_metrics = {
            'control-flow': {'2gd': metrics['2gd'], '3gd': metrics['3gd']},
            'time': {'ctd': metrics['ctd'], 'car': metrics['car']},
            'resource-flow': {'r2gd': metrics['r2gd'], 'r3gd': metrics['r3gd']},
            'generalization': {'ctd_entropy': metrics['ctd_entropy'], 'etd_entropy': metrics['etd_entropy']},
            'kpi_comparison': {
                'real': compute_log_kpis(df_event_log),
                'simulated': compute_log_kpis(simulated_event_log),
                'charts': compute_log_charts(df_event_log, simulated_event_log),
            },
        }
        return self.prosit_metrics

    def run_simulation(self, n_traces=100, start_timestamp=None):
        """Run simulation using ProSiT SimulatorEngine.
        
        Args:
            n_traces: Number of traces to simulate
            start_timestamp: Starting timestamp for simulation
            
        Returns:
            DataFrame containing the simulated event log
        """
        try:
            if not self.prosit_params:
                raise ValueError("No parameters available. Call discover_parameters first.")
            
            if start_timestamp is None:
                start_timestamp = datetime.now()
            
            # Create simulator engine
            net, im, fm = self.process_model["net"], self.process_model["initial_marking"], self.process_model["final_marking"]
            params = SimulatorParameters(net, im, fm)
            params.from_dict(self.prosit_params)
            simulator = SimulatorEngine(params)
            
            # Run simulation
            logger.info(f"Running simulation with {n_traces} traces starting at {start_timestamp}")
            result_df = simulator.apply(n_traces=n_traces, t_start=start_timestamp)
            
            logger.info(f"Simulation completed. Generated {len(result_df)} events")
            return result_df
            
        except Exception as e:
            logger.error(f"Error running simulation: {str(e)}")
            raise

    def save_parameters_to_json(self, output_path):
        """Save parameters to JSON using ProSiT's to_json method"""
        try:
            if not self.prosit_params:
                raise ValueError("No parameters discovered yet. Call discover_parameters first.")
            
            net, im, fm = self.process_model["net"], self.process_model["initial_marking"], self.process_model["final_marking"]
            params = SimulatorParameters(net, im, fm)
            params.from_dict(self.prosit_params)
            params.to_json(output_path)
            logger.info(f"Parameters saved to {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error saving parameters: {str(e)}")
            raise
    
    def load_parameters_from_json_file(self, json_path):
        """Load parameters directly from JSON file and convert to app format"""
        try:
            net, im, fm = self.process_model["net"], self.process_model["initial_marking"], self.process_model["final_marking"]
            params = SimulatorParameters(net, im, fm)
            params.from_json(json_path)
            logger.info(f"Loading parameters from JSON file: {json_path}")
            self.prosit_params = params.to_dict()
            return self._convert_prosit_to_app_format()
            
        except Exception as e:
            logger.error(f"Error loading parameters from JSON file: {str(e)}")
            raise
   
    def _convert_prosit_to_app_format(self):
        """Convert ProSiT parameters to application format.

        Every distribution goes through ``prosit_entry_to_app``, the exact
        inverse of what the parameters endpoints apply when the UI sends the
        document back.

        Returns:
            Dictionary containing parameters formatted for the web application
        """
        prosit_params = self.prosit_params

        def entries_to_app(entries):
            converted = {}
            for name, entry in entries.items():
                if isinstance(entry, dict):
                    converted[name] = prosit_entry_to_app(entry)
                elif entry is not None:
                    # Not a shape prosit-pm writes; show it as a fixed value.
                    logger.warning("Unknown distribution format for %s: %r", name, entry)
                    converted[name] = prosit_entry_to_app({'dist_name': 'fixed', 'params': [1.0]})
            return converted

        execution_time_params = entries_to_app(
            prosit_params['execution_time_params']['execution_time_distributions']
        )
        resource_waiting_times = entries_to_app(
            prosit_params['waiting_time_params']['waiting_time_distributions']
        )

        resource_params = prosit_params['resource_params']
        resources = resource_params['resources']
        max_concurrency = resource_params.get('max_concurrency', {r: 1 for r in resources})

        arrival_dist = prosit_params['arrival_params']['arrival_time_distributions']
        arrival_calendar = prosit_params['arrival_params']['arrival_calendar']
        inter_arrival_time = {}
        if isinstance(arrival_dist, dict):
            if 'params' not in arrival_dist:
                # Decision tree: shown as it is.
                inter_arrival_time = {'distribution': arrival_dist, 'calendar': arrival_calendar}
            else:
                inter_arrival_time = {**prosit_entry_to_app(arrival_dist), 'calendar': arrival_calendar}

        # Data Attributes — prosit-pm (since 1.0.2) wraps the dict in
        # {"mode": ..., "data": {...}} and renames keys (dist_name→dist,
        # min_value→min, max_value→max, mean_value→mean). Older logs may
        # still have the legacy flat shape; handle both.
        data_attribute_params = prosit_params.get('data_attribute_params', {})
        app_data_attributes = {
            "label_data_attributes": data_attribute_params.get("label_data_attributes", []),
            "label_data_attributes_categorical": data_attribute_params.get("label_data_attributes_categorical", []),
            "attribute_values_label_categorical": data_attribute_params.get("attribute_values_label_categorical", {}),
            "distribution_data_attributes": {},
            # Defaults to 'distribution'; flipped below if prosit-pm wrote
            # empirical samples instead.
            "distribution_mode": 'distribution',
        }

        raw_dist_attrs = data_attribute_params.get("distribution_data_attributes") or {}
        mode = None
        if 'mode' in raw_dist_attrs and 'data' in raw_dist_attrs:
            mode = raw_dist_attrs.get('mode')
            prosit_dist_attrs = raw_dist_attrs.get('data') or {}
        else:
            prosit_dist_attrs = raw_dist_attrs

        if mode == 'empirical':
            # Empirical mode keys are stringified tuples of joint values, not
            # per-attribute dicts. We can't surface them as editable rows, so
            # we just expose the attribute names with a read-only marker. The
            # underlying empirical samples are preserved on save.
            app_data_attributes['distribution_mode'] = 'empirical'
            for attr_name in app_data_attributes['label_data_attributes']:
                app_data_attributes['distribution_data_attributes'][attr_name] = {
                    'type': 'empirical',
                    'readonly': True,
                }
            # Skip the per-attribute conversion loop below.
            prosit_dist_attrs = {}

        categorical_attrs = data_attribute_params.get("label_data_attributes_categorical", [])

        for attr, params_dict in prosit_dist_attrs.items():
            if attr in categorical_attrs:
                # Normalize categorical entries to a stable shape so the UI
                # can rely on params.values. prosit-pm sometimes writes
                # ``{"type": 0, "values": {...}}`` (truthy garbage), and
                # legacy logs may store the bare ``{cat: prob}`` dict.
                if isinstance(params_dict, dict) and 'values' in params_dict:
                    values = params_dict.get('values') or {}
                elif isinstance(params_dict, dict):
                    values = params_dict
                else:
                    values = {}
                app_data_attributes["distribution_data_attributes"][attr] = {
                    'type': 'categorical',
                    'values': values,
                }
                continue
            entry = attribute_entry_from_prosit(params_dict)
            if entry is not None:
                app_data_attributes["distribution_data_attributes"][attr] = prosit_entry_to_app(entry)

        parameters = {
            'process_model': {
                'activities': self.process_model['activities'],
                'places': self.process_model['places'],
                'transitions': self.process_model['transitions'],
                'transition_label_map': self.process_model.get('transition_label_map', {}),
                'silent_transitions': self.process_model.get('silent_transitions', []),
                'dot': self.process_model['dot'],
                'nodes': self.process_model['nodes'],
                'fitness': self.process_model['fitness'],
                'precision': self.process_model['precision'],
                'f_measure': self.process_model['f_measure']
            },
            'prosit_metrics': self.prosit_metrics,
            # How the model was discovered: it decides what a decision tree
            # can test (see tree-features.js). Shown, never edited.
            'model_options': {
                'rules_mode': bool(prosit_params.get('rules_mode', False)),
                'use_workload_features': bool(prosit_params.get('use_workload_features', False)),
            },
            'transition_params': {
                'transition_weights': prosit_params["transition_params"]["transition_weights"]
            },
            'execution_time_params': {
                'activity_durations': execution_time_params
            },
            'resource_params': {
                'resources': resources,
                'resource_weights': resource_params['resource_weights'],
                'max_concurrency': max_concurrency,
                'act_to_resources': resource_params['act_to_resources'],
                'calendars': resource_params['calendars']
            },
            'waiting_time_params': {
                'resource_waiting_times': resource_waiting_times
            },
            'inter_arrival_params': {
                'inter_arrival_time': inter_arrival_time
            },
            'data_attribute_params': app_data_attributes
        }

        multitasking_count = sum(1 for v in max_concurrency.values() if v > 1)
        logger.info(
            "Converted parameters: %d resources, %d activities with execution times, %d multitasking resources",
            len(resources), len(execution_time_params), multitasking_count,
        )
        return parameters
