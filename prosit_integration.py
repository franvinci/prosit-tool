import logging
from datetime import datetime

import pandas as pd
import pm4py
from pm4py.visualization.petri_net import visualizer as pn_visualizer
from pm4py.algo.evaluation.replay_fitness import algorithm as fitness_evaluator
from pm4py.algo.evaluation.precision import algorithm as precision_evaluator

from prosit.simulator import SimulatorParameters, SimulatorEngine
from evaluation import evaluate

logger = logging.getLogger(__name__)

class ProSiTIntegration:
    """Integration layer for ProSiT library functionality.
    
    This class provides methods to discover process models, extract parameters,
    and run simulations using the ProSiT framework.
    """
    
    def __init__(self):
        self.process_model = None
        self.event_log = None
        self.prosit_params = None
        self.prosit_metrics = None
    
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
            net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(self.event_log, noise_threshold=noise_threshold)
            
            
            # Extract activities, transitions, and places from the net
            activities = []
            transitions = []
            places = []
            
            for transition in net.transitions:
                transitions.append(transition.name)
                if transition.label:  # Skip silent transitions
                    activities.append(transition.label)
            
            for place in net.places:
                places.append(place.name)

            # Create mapping from transition names to IDs
            map_transitionName_to_id = {}
            for t in net.transitions:
                key = t.label if t.label else t.name
                map_transitionName_to_id[key] = str(id(t))
            
            # Generate visualization
            visualization_svg = self._generate_petri_net_visualization(net, initial_marking, final_marking)

            fitness = fitness_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            fitness = fitness['averageFitness']
            precision = precision_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            f_measure = 2*fitness*precision/(fitness+precision)
            
            # Create process model structure
            self.process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'map_transitionName_to_id': map_transitionName_to_id,
                'fitness': fitness,
                'precision': precision,
                'f_measure': f_measure,
                # 'start_activities': activities[:1] if activities else [],
                # 'end_activities': activities[-1:] if activities else [],
                'visualization': visualization_svg,
                'net': net,
                'initial_marking': initial_marking,
                'final_marking': final_marking
            }
            
            logger.info(f"Discovered process model with {len(activities)} activities")
            
        except Exception as e:
            logger.error(f"Error discovering process model: {str(e)}")
            raise
    
    def import_petri_net_from_pnml(self, pnml_file_path):
        """
        Import Petri net structure from PNML file.
        
        Used when you have a separate Petri net model and want to discover
        parameters from an XES event log.
        
        Args:
            pnml_file_path: Path to the PNML file containing the Petri net
            
        Updates:
            self.process_model: Dictionary containing the imported process model
        """
        try:
            logger.info(f"Importing Petri net structure from {pnml_file_path}")
            
            # Import PNML file using PM4Py
            net, initial_marking, final_marking = pm4py.read_pnml(pnml_file_path)
            
            
            # Extract activities, transitions, and places from the net
            activities = []
            transitions = []
            places = []
            
            for transition in net.transitions:
                transitions.append(transition.name)
                if transition.label:  # Skip silent transitions
                    activities.append(transition.label)
            
            for place in net.places:
                places.append(place.name)
            
            map_transitionName_to_id = dict()
            for t in net.transitions:
                if t.label:
                    map_transitionName_to_id[t.label] = str(id(t))
                else:
                    map_transitionName_to_id[t.name] = str(id(t))

            
            # Generate visualization
            visualization_svg = self._generate_petri_net_visualization(net, initial_marking, final_marking)
            
            fitness = fitness_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            fitness = fitness['averageFitness']
            precision = precision_evaluator.apply(self.event_log, net, initial_marking, final_marking)
            f_measure = 2*fitness*precision/(fitness+precision)

            # Create process model structure (without parameters)
            self.process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'map_transitionName_to_id': map_transitionName_to_id,
                'fitness': fitness,
                'precision': precision,
                'f_measure': f_measure,
                'visualization': visualization_svg,
                'net': net,
                'initial_marking': initial_marking,
                'final_marking': final_marking
            }
            
            logger.info(f"PNML Petri net imported successfully: {len(activities)} activities, {len(places)} places")
            
        except Exception as e:
            logger.error(f"Failed to import Petri net from PNML: {str(e)}")
            raise e

    def discover_parameters(self, max_depth_tree=0, incremental_discovery=False, grace_period=1000):
        """
        Discover simulation parameters using ProSiT library.
        
        Args:
            max_depth_tree: Maximum depth for decision trees (0 disables rules mode)
            incremental_discovery: Whether to use incremental learning algorithms
            grace_period: Number of events to wait before starting incremental learning
            
        Returns:
            Dictionary containing discovered parameters in application format
        """
        try:
            logger.info(f"Discovering parameters from Event Log")
            
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
            try:
                self.prosit_params.discover_from_eventlog(self.event_log, max_depth_tree=max_depth_tree, incremental_discovery=incremental_discovery, grace_period=grace_period, verbose=True)
                logger.info("ProSiT parameter discovery completed successfully")
            except Exception as discovery_error:
                logger.error(f"ProSiT discovery_from_eventlog failed: {str(discovery_error)}")
                logger.info("Creating fallback parameters due to ProSiT discovery failure")
                return self._create_fallback_parameters()
            
            # Convert ProSiT parameters to our application format
            self.prosit_params = self.prosit_params.to_dict()
            logger.info(f"ProSiT parameters converted to dictionary")
            
            df_event_log = pm4py.convert_to_dataframe(self.event_log)

            df_event_log['case:concept:name'] = df_event_log['case:concept:name'].astype(str)
            df_event_log['time:timestamp'] = pd.to_datetime(df_event_log['time:timestamp'])
            df_event_log['start:timestamp'] = pd.to_datetime(df_event_log['start:timestamp'])

            df_event_log.sort_values(by=['start:timestamp', 'time:timestamp'], inplace=True)
            df_event_log.reset_index(drop=True, inplace=True)
            start_t = df_event_log.iloc[0]['start:timestamp']
            simulated_event_log = self.run_simulation(n_traces = len(self.event_log), start_timestamp=start_t)
            logger.info("Simulation completed")
            metrics = evaluate(df_event_log, simulated_event_log, metrics_labels=['2gd', '3gd', 'ctd', 'car', 'r2gd', 'r3gd', 'ctd_entropy', 'etd_entropy'])
            self.prosit_metrics = {
                'control-flow': {'2gd': metrics['2gd'], '3gd': metrics['3gd']},
                'time': {'ctd': metrics['ctd'], 'car': metrics['car']},
                'resource-flow': {'r2gd': metrics['r2gd'], 'r3gd': metrics['r3gd']},
                'generalization': {'ctd_entropy': metrics['ctd_entropy'], 'etd_entropy': metrics['etd_entropy']}
            }
            return self._convert_prosit_to_app_format()
            
        except Exception as e:
            logger.error(f"Error discovering parameters: {str(e)}")
            raise

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

    def _generate_petri_net_visualization(self, net, initial_marking, final_marking):
        """Generate Petri net visualization using PM4Py and return as SVG"""
        try:
            # Generate visualization with custom styling
            gviz = pn_visualizer.apply(net, initial_marking, final_marking, parameters={
                pn_visualizer.Variants.WO_DECORATION.value.Parameters.FORMAT: "svg"
            })
            
            # Get SVG content
            svg_content = gviz.pipe(format='svg', encoding='utf-8')
            
            # Enhance SVG with styling
            enhanced_svg = self._enhance_svg_visualization(svg_content)
            
            return enhanced_svg
        
        except Exception as e:
            logger.error(f"Error generating visualization: {str(e)}")
            return None

    def _enhance_svg_visualization(self, svg_content):
        """Enhance SVG with improved styling for purple/green theme"""
        try:
            # Add basic styling for better appearance
            enhanced_svg = svg_content.replace(
                '<svg',
                '''<svg style="max-width: 100%; height: auto; background: white; border-radius: 8px;"'''
            )
            
            # Improve styling of transitions and places with purple/green theme
            enhanced_svg = enhanced_svg.replace(
                'fill="lightblue"',
                'fill="#6f42c1" stroke="#5a2d91" stroke-width="2"'
            )
            enhanced_svg = enhanced_svg.replace(
                'fill="orange"',
                'fill="#28a745" stroke="#1e7e34" stroke-width="2"'
            )
            enhanced_svg = enhanced_svg.replace(
                'fill="black"',
                'fill="#333" stroke="#444" stroke-width="1"'
            )
            
            # Add basic CSS for better text appearance
            style_css = '''
            <defs>
            <style type="text/css">
            <![CDATA[
            text {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 12px;
            }
            ]]>
            </style>
            </defs>
            '''
            
            # Insert CSS after opening SVG tag
            enhanced_svg = enhanced_svg.replace('<svg', style_css + '<svg', 1)
            
            return enhanced_svg
            
        except Exception as e:
            logger.error(f"Error enhancing SVG: {str(e)}")
            return svg_content

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
        
        Returns:
            Dictionary containing parameters formatted for the web application
        """
        try:
            logger.info("Converting ProSiT parameters to application format")

            # Get transition weights from ProSiT parameters
            transition_weights = self.prosit_params["transition_params"]["transition_weights"]
            
            # Get execution time distributions from ProSiT parameters
            execution_time_params = {}
            exec_time_dists = self.prosit_params['execution_time_params']['execution_time_distributions']
            logger.info(f"Found execution time distributions for {len(exec_time_dists)} activities")
            
            # Debug: Check the actual structure of execution_time_distributions
            if exec_time_dists:
                logger.info(f"Sample execution time entry: {list(exec_time_dists.items())[0] if exec_time_dists else 'None'}")
            
            for activity, dist_info in exec_time_dists.items():
                logger.info(f"Processing execution time for activity: {activity}, dist_info type: {type(dist_info)}")
                if isinstance(dist_info, dict):
                    if 'params' not in dist_info:
                        execution_time_params[activity] = dist_info
                        logger.info(f"Activity {activity} DT: {dist_info}")
                    else:
                        params = dist_info.get('params', [1.0])
                        execution_time_params[activity] = {
                            'distribution': dist_info.get('dist_name', 'fixed'),
                            'parameters': self._convert_prosit_params_to_app(dist_info.get('dist_name', 'fixed'), params, dist_info.get('min_value', 1.0), dist_info.get('max_value', 1.0), dist_info.get('mean_value', params[0] if params and len(params) > 0 else 1.0))
                        }
                        logger.info(f"Activity {activity}: {dist_info.get('dist_name', 'fixed')} with params {params}")
                elif dist_info is not None:
                    # Handle other non-dict formats
                    logger.info(f"Unknown execution time data format for {activity}: {dist_info}")
                    execution_time_params[activity] = {
                        'distribution': 'fixed',
                        'parameters': {
                            'params': [1.0],
                            'min_value': 1.0,
                            'max_value': 1.0,
                            'mean_value': 1.0
                        }
                    }
            
            # Get resources and activity-resource assignments
            resources = self.prosit_params['resource_params']['resources']
            resource_weights = self.prosit_params['resource_params']['resource_weights']
            act_to_resources = self.prosit_params['resource_params']['act_to_resources']
            multitasking_resources = self.prosit_params['resource_params']['multitasking_resource']
            
            # Get calendars and convert numeric day keys to day names
            calendars = self.prosit_params['resource_params']['calendars']
            logger.info(f"Found calendars for {len(calendars)} resources: {list(calendars.keys())}")
            
            # Get waiting time distributions (resource-specific)
            resource_waiting_times = {}
            wait_time_dists = self.prosit_params['waiting_time_params']['waiting_time_distributions']
            logger.info(f"Found waiting time distributions for {len(wait_time_dists)} resources")
            
            for resource, dist_info in wait_time_dists.items():
                logger.info(f"Processing waiting time for resource: {resource}, dist_info type: {type(dist_info)}")
                if isinstance(dist_info, dict):
                    if 'params' not in dist_info:
                        resource_waiting_times[resource] = dist_info
                        logger.info(f"Resource {resource} DT: {dist_info}")
                    else:
                        params = dist_info.get('params', [1.0])
                        resource_waiting_times[resource] = {
                            'distribution': dist_info.get('dist_name', 'fixed'),
                            'parameters': self._convert_prosit_params_to_app(dist_info.get('dist_name', 'fixed'), params, dist_info.get('min_value', 1.0), dist_info.get('max_value', 1.0), dist_info.get('mean_value', params[0] if params and len(params) > 0 else 1.0))
                        }
                        logger.info(f"Resource {resource}: {dist_info.get('dist_name', 'fixed')} waiting time with params {params}")
                elif dist_info is not None:
                    # Handle other non-dict formats
                    logger.info(f"Unknown waiting time data format for {resource}: {dist_info}")
                    resource_waiting_times[resource] = {
                        'distribution': 'fixed',
                        'parameters': {
                            'params': [1.0],
                            'min_value': 1.0,
                            'max_value': 1.0,
                            'mean_value': 1.0
                        }
                    }
            
            # Get arrival time parameters
            arrival_dist = self.prosit_params['arrival_params']['arrival_time_distributions']
            arrival_calendar = self.prosit_params['arrival_params']['arrival_calendar']
            
            inter_arrival_time = {}
            if isinstance(arrival_dist, dict):
                if 'params' not in arrival_dist:
                    inter_arrival_time = {'distribution': arrival_dist, 'calendar': arrival_calendar}
                    logger.info(f"Arrival time: {arrival_dist}")
                else:
                    arr_params = arrival_dist.get('params', [1.0])
                    min_val = arrival_dist.get('min_value', 1.0)
                    max_val = arrival_dist.get('max_value', 1.0)
                    mean_val = arrival_dist.get('mean_value', (arr_params[0] if arr_params else 1.0))
                    inter_arrival_time = {
                        'distribution': arrival_dist.get('dist_name', 'fixed'),
                        'parameters': self._convert_prosit_params_to_app(arrival_dist.get('dist_name', 'fixed'), arr_params, min_val, max_val, mean_val),
                        'calendar': arrival_calendar
                    }
                    logger.info(f"Arrival time: {arrival_dist.get('dist_name', 'fixed')} with params {arr_params}")

            # Data Attributes
            data_attribute_params = self.prosit_params.get('data_attribute_params', {})
            app_data_attributes = {
                "label_data_attributes": data_attribute_params.get("label_data_attributes", []),
                "label_data_attributes_categorical": data_attribute_params.get("label_data_attributes_categorical", []),
                "attribute_values_label_categorical": data_attribute_params.get("attribute_values_label_categorical", {}),
                "distribution_data_attributes": {}
            }

            prosit_dist_attrs = data_attribute_params.get("distribution_data_attributes", {})
            categorical_attrs = data_attribute_params.get("label_data_attributes_categorical", [])

            for attr, params_dict in prosit_dist_attrs.items():
                if attr in categorical_attrs:
                    app_data_attributes["distribution_data_attributes"][attr] = params_dict
                else:
                    dist_name = params_dict.get('dist_name', 'fixed')
                    params = params_dict.get('params', [1.0])
                    min_val = params_dict.get('min_value', 1.0)
                    max_val = params_dict.get('max_value', 1.0)
                    mean_val = params_dict.get('mean_value', params[0] if params else 1.0)
                    app_data_attributes["distribution_data_attributes"][attr] = {
                        'distribution': dist_name,
                        'parameters': self._convert_prosit_params_to_app(dist_name, params, min_val, max_val, mean_val)
                    }

            # Build the final parameters structure
            parameters = {
                'process_model': {
                    'activities': self.process_model['activities'],
                    'places': self.process_model['places'],
                    'transitions': self.process_model['transitions'],
                    'map_transitionName_to_id': self.process_model['map_transitionName_to_id'],
                    'visualization': self.process_model['visualization'],
                    'fitness': self.process_model['fitness'],
                    'precision': self.process_model['precision'],
                    'f_measure': self.process_model['f_measure']
                },
                'prosit_metrics': self.prosit_metrics,
                'transition_params': {
                    'transition_weights': transition_weights
                },
                'execution_time_params': {
                    'activity_durations': execution_time_params
                },
                'resource_params': {
                    'resources': resources,
                    'resource_weights': resource_weights,
                    'multitasking_resource': multitasking_resources,
                    'act_to_resources': act_to_resources,
                    'calendars': calendars
                },
                'waiting_time_params': {
                    'resource_waiting_times': resource_waiting_times
                },
                'inter_arrival_params': {
                    'inter_arrival_time': inter_arrival_time
                },
                'data_attribute_params': app_data_attributes
            }
            
            logger.info(f"Converted parameters: {len(resources)} resources, {len(execution_time_params)} activities with execution times, {len(multitasking_resources)} multitasking resources")
            logger.info(f"Activities with execution times: {list(execution_time_params.keys())}")
            logger.info(f"Resources with waiting times: {list(resource_waiting_times.keys())}")
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error converting ProSiT parameters: {str(e)}")
            logger.error(f"ProSiT params attributes: {dir(self.prosit_params)}")
            raise

    def _convert_prosit_params_to_app(self, dist_name, params, min_val, max_val, mean_val):
        """Convert ProSiT parameter format to application format"""
        try:
            app_params = {
                'min_value': float(min_val),
                'max_value': float(max_val),
                'mean_value': float(mean_val)
            }
            
            if dist_name == 'fixed':
                app_params['value'] = float(params[0]) if params else 1.0
                
            elif dist_name == 'norm':
                app_params['mean'] = float(params[0]) if len(params) > 0 else 15.0
                app_params['std'] = float(params[1]) if len(params) > 1 else 5.0
                
            elif dist_name == 'expon':
                # ProSiT expon params: [loc, scale] - use scale as mean
                scale_val = float(params[1]) if len(params) > 1 else mean_val
                app_params['scale'] = scale_val
                # Add mean for interface display (same as scale for exponential)
                app_params['mean'] = scale_val
                
            elif dist_name == 'uniform':
                # ProSiT uniform params: [min, max] 
                if len(params) >= 2:
                    app_params['min'] = float(params[0])
                    app_params['max'] = float(params[1])
                else:
                    app_params['min'] = float(min_val)
                    app_params['max'] = float(max_val)
            
            return app_params
            
        except Exception as e:
            logger.error(f"Error converting parameters for {dist_name}: {str(e)}")
            return {'mean': 15.0, 'std': 2.0, 'min_value': 0.0, 'max_value': 60.0, 'mean_value': 15.0}

    def _create_fallback_parameters(self):
        """Create simplified parameters when ProSiT discovery fails"""
        try:
            logger.info("Creating fallback parameters...")
            
            # Initialize ProSiT parameters with basic structure
            self.prosit_params = dict()

            # Set basic resources from event log if available
            resources = []
            try:
                if self.event_log and len(self.event_log) > 0:
                    for trace in self.event_log:
                        for event in trace:
                            if hasattr(event, 'get') and event.get('org:resource'):
                                resource = event['org:resource']
                                if resource not in resources:
                                    resources.append(resource)
            except Exception:
                pass
            
            # If no resources found, create default ones
            if not resources:
                resources = ['Resource_1', 'Resource_2', 'Resource_3']

            standard_calendar = {}
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            for day in days:
                standard_calendar[day] = {str(hour): True for hour in range(24)}

            standard_distribution = {
                    'dist_name': 'normal',
                    'params': [15.0, 5.0],
                    'min_value': 1.0,
                    'max_value': 60.0
                }

            self.prosit_params = {
                "transition_params": {
                    "transition_weights": {
                        t: 0.5 for t in self.process_model['transitions']
                    }
                },
                "resource_params": {
                    "resources": resources,
                    "multitasking_resource": [],
                    "act_to_resources": {a: resources for a in self.process_model['activities']},
                    "resource_weights": {r: 1.0 / len(resources) for r in resources},
                    "calendars": {r: standard_calendar for r in resources}
                },
                "arrival_params": {
                    "arrival_calendar": standard_calendar,
                    "arrival_time_distributions": standard_distribution
                },
                "execution_time_params": {
                    "execution_time_distributions": {a: standard_distribution for a in self.process_model['activities']}
                },
                "waiting_time_params": {
                    "waiting_time_distributions": {r: standard_distribution for r in resources}
                },
                "data_attribute_params": {
                    "label_data_attributes": [],
                    "label_data_attributes_categorical": [],
                    "attribute_values_label_categorical": [],
                    "distribution_data_attributes": {}
                }
            }
            
            logger.info(f"Created fallback parameters with {len(resources)} resources and {len(self.process_model['activities'])} activities")
        
            return self.prosit_params
            
        except Exception as e:
            logger.error(f"Error creating fallback parameters: {str(e)}")
            raise