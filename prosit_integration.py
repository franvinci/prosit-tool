import os
import json
import logging
import tempfile
from datetime import datetime
import pm4py
from pm4py.visualization.petri_net import visualizer as pn_visualizer
from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.log.importer.xes import importer as xes_importer

# ProSiT imports
from prosit.simulator import SimulatorParameters, SimulatorEngine
from prosit.utils.save_and_load_utils import transition_to_name, name_to_transition

logger = logging.getLogger(__name__)

class ProSiTIntegration:
    """Integration layer for ProSiT library functionality"""
    
    def __init__(self):
        self.supported_formats = ['.xes', '.pnml']
        self.petri_net = None
        self.initial_marking = None
        self.final_marking = None
        self.transition_mappings = {}
        self.prosit_params = None
    
    def discover_process_model(self, xes_file_path, noise_threshold=0.2):
        """
        Discover process model using PM4Py inductive miner
        Returns: process model structure with visualization
        """
        try:
            logger.info(f"Discovering process model from {xes_file_path} with noise threshold {noise_threshold}")
            
            # Load event log from XES file using proper XES importer
            event_log = xes_importer.apply(xes_file_path)
            logger.info(f"Loaded {len(event_log)} traces from XES file")
            
            # Apply inductive miner to discover Petri net
            net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(event_log, noise_threshold=noise_threshold)
            
            # Store the net and markings for later use
            self.petri_net = net
            self.initial_marking = initial_marking
            self.final_marking = final_marking
            
            # Extract activities from the net and create transition mappings
            activities = []
            transitions = []
            places = []
            self.transition_mappings = {}
            
            for transition in net.transitions:
                if transition.label:  # Skip silent transitions
                    transition_name = transition_to_name(transition)
                    activities.append(transition_name)
                    transitions.append(transition.name)
                    # Create bidirectional mapping
                    self.transition_mappings[transition_name] = transition
                    self.transition_mappings[transition.name] = transition
            
            for place in net.places:
                places.append(place.name)
            
            # Generate visualization
            visualization_svg = self._generate_petri_net_visualization(net, initial_marking, final_marking)
            
            # Create process model structure
            process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'start_activities': activities[:1] if activities else [],
                'end_activities': activities[-1:] if activities else [],
                'visualization': visualization_svg,
                'net': net,
                'initial_marking': initial_marking,
                'final_marking': final_marking,
                'event_log': event_log
            }
            
            logger.info(f"Discovered process model with {len(activities)} activities")
            return process_model
            
        except Exception as e:
            logger.error(f"Error discovering process model: {str(e)}")
            raise
    
    def discover_parameters(self, xes_file_path, process_model=None):
        """
        Discover simulation parameters using ProSiT library
        """
        try:
            logger.info(f"Discovering parameters from {xes_file_path}")
            
            if not process_model:
                process_model = self.discover_process_model(xes_file_path)
            
            # Get the event log, net, and markings
            event_log = process_model['event_log']
            net = process_model['net']
            initial_marking = process_model['initial_marking']
            final_marking = process_model['final_marking']
            
            # Create ProSiT parameters instance
            self.prosit_params = SimulatorParameters(net, initial_marking, final_marking)
            self.current_net = net  # Store for later use
            
            # Discover parameters from event log (max_depth_tree=0 disables rules mode)
            logger.info("Starting ProSiT parameter discovery...")
            try:
                self.prosit_params.discover_from_eventlog(event_log, max_depth_tree=0, verbose=True)
                logger.info("ProSiT parameter discovery completed successfully")
            except Exception as discovery_error:
                logger.error(f"ProSiT discovery_from_eventlog failed: {str(discovery_error)}")
                logger.error(f"Event log type: {type(event_log)}")
                if hasattr(event_log, '__len__'):
                    logger.error(f"Event log length: {len(event_log)}")
                
                # Try to create simplified parameters when ProSiT discovery fails
                logger.info("Creating fallback parameters due to ProSiT discovery failure")
                self._create_fallback_parameters(event_log, net, initial_marking, final_marking)
            
            # Convert ProSiT parameters to our application format
            parameters = self._convert_prosit_to_app_format(self.prosit_params, net)
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error discovering parameters: {str(e)}")
            raise
    
    def save_parameters_to_json(self, output_path):
        """Save parameters to JSON using ProSiT's to_json method"""
        try:
            if not self.prosit_params:
                raise ValueError("No parameters discovered yet. Call discover_parameters first.")
            
            self.prosit_params.to_json(output_path)
            logger.info(f"Parameters saved to {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error saving parameters: {str(e)}")
            raise
    
    def load_parameters_from_json(self, json_path):
        """Load parameters from JSON using ProSiT's from_json method"""
        try:
            if not self.petri_net:
                raise ValueError("No process model loaded. Call discover_process_model first.")
            
            if not self.petri_net or not self.initial_marking or not self.final_marking:
                raise ValueError("Process model components are missing.")
            
            self.prosit_params = SimulatorParameters(
                self.petri_net, 
                self.initial_marking, 
                self.final_marking
            )
            self.prosit_params.from_json(json_path)
            
            logger.info(f"Parameters loaded from {json_path}")
            return self._convert_prosit_to_app_format(self.prosit_params, getattr(self, 'current_net', None))
            
        except Exception as e:
            logger.error(f"Error loading parameters: {str(e)}")
            raise
    
    def run_simulation(self, n_traces=100, start_timestamp=None):
        """Run simulation using ProSiT SimulatorEngine"""
        try:
            if not self.prosit_params:
                raise ValueError("No parameters available. Call discover_parameters first.")
            
            if start_timestamp is None:
                start_timestamp = datetime.now()
            
            # Create simulator engine
            simulator = SimulatorEngine(self.prosit_params)
            
            # Run simulation
            logger.info(f"Running simulation with {n_traces} traces starting at {start_timestamp}")
            result_df = simulator.apply(n_traces=n_traces, t_start=start_timestamp)
            
            logger.info(f"Simulation completed. Generated {len(result_df)} events")
            return result_df
            
        except Exception as e:
            logger.error(f"Error running simulation: {str(e)}")
            raise
    
    def load_parameters_from_json_file(self, json_path):
        """Load parameters directly from JSON file and convert to app format"""
        try:
            with open(json_path, 'r') as f:
                prosit_json = json.load(f)
            
            logger.info(f"Loading parameters from JSON file: {json_path}")
            return self._convert_prosit_json_to_app_format(prosit_json)
            
        except Exception as e:
            logger.error(f"Error loading parameters from JSON file: {str(e)}")
            raise

    def _convert_prosit_json_to_app_format(self, prosit_json):
        """Convert ProSiT JSON format to our application's format"""
        try:
            logger.info("Converting ProSiT JSON to application format...")
            
            # Extract transition weights
            transition_weights = prosit_json.get('transition_params', {}).get('transition_weights', {})
            
            # Extract execution time parameters 
            execution_time_params = {}
            exec_time_dists = prosit_json.get('execution_time_params', {}).get('execution_time_distributions', {})
            
            for activity, dist_info in exec_time_dists.items():
                dist_name = dist_info.get('dist_name', 'norm')
                params = dist_info.get('params', [10.0, 2.0])
                min_val = dist_info.get('min_value', 0.0)
                max_val = dist_info.get('max_value', 100.0)
                mean_val = dist_info.get('mean_value', 10.0)
                
                execution_time_params[activity] = {
                    'distribution': dist_name,
                    'parameters': self._convert_prosit_params_to_app(dist_name, params, min_val, max_val, mean_val)
                }
            
            # Extract resource parameters
            resource_params = prosit_json.get('resource_params', {})
            resources = resource_params.get('resources', [])
            resource_weights = resource_params.get('resource_weights', {})
            multitasking_resources = resource_params.get('multitasking_resource', [])
            act_to_resources = resource_params.get('act_to_resources', {})
            calendars = resource_params.get('calendars', {})
            
            # Convert act_to_resources to act_resource_prob format (with equal probabilities)
            act_resource_prob = {}
            for activity, assigned_resources in act_to_resources.items():
                if assigned_resources:
                    prob_per_resource = 1.0 / len(assigned_resources)
                    act_resource_prob[activity] = {
                        resource: prob_per_resource for resource in assigned_resources
                    }
            
            logger.info(f"Extracted resource data: {len(resources)} resources, {len(resource_weights)} with weights, {len(act_to_resources)} activities with assignments")
            
            # Extract waiting time parameters
            waiting_time_params = {}
            wait_time_dists = prosit_json.get('waiting_time_params', {}).get('waiting_time_distributions', {})
            
            for resource, dist_info in wait_time_dists.items():
                dist_name = dist_info.get('dist_name', 'expon')
                params = dist_info.get('params', [0.0, 120.0])
                min_val = dist_info.get('min_value', 0.0)
                max_val = dist_info.get('max_value', 1000.0)
                mean_val = dist_info.get('mean_value', 120.0)
                
                waiting_time_params[resource] = {
                    'distribution': dist_name,
                    'parameters': self._convert_prosit_params_to_app(dist_name, params, min_val, max_val, mean_val)
                }
            
            # Extract inter-arrival time parameters
            inter_arrival_params = prosit_json.get('inter_arrival_params', {})
            
            # Create process model info (will be loaded separately)
            process_model = {
                'activities': list(exec_time_dists.keys()),
                'transitions': list(transition_weights.keys()),
                'places': []  # Will be filled when process model is loaded
            }
            
            parameters = {
                'process_model': process_model,
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
                    'act_resource_prob': act_resource_prob,
                    'calendars': calendars
                },
                'waiting_time_params': {
                    'waiting_time': waiting_time_params
                },
                'inter_arrival_params': inter_arrival_params
            }
            
            logger.info(f"Converted JSON parameters: {len(resources)} resources, {len(execution_time_params)} activities with execution times, {len(multitasking_resources)} multitasking resources")
            logger.info(f"Resource weights: {len(resource_weights)} resources have weights")
            logger.info(f"Activity assignments: {len(act_resource_prob)} activities have resource assignments")
            if act_resource_prob:
                sample_activity = list(act_resource_prob.keys())[0]
                logger.info(f"Sample assignment - {sample_activity}: {act_resource_prob[sample_activity]}")
            return parameters
            
        except Exception as e:
            logger.error(f"Error converting ProSiT JSON to app format: {str(e)}")
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
                app_params['value'] = float(params[0]) if params else 10.0
                
            elif dist_name == 'norm':
                app_params['mean'] = float(params[0]) if len(params) > 0 else 10.0
                app_params['std'] = float(params[1]) if len(params) > 1 else 2.0
                
            elif dist_name == 'expon':
                app_params['scale'] = float(params[1]) if len(params) > 1 else 10.0
                
            elif dist_name == 'lognorm':
                app_params['s'] = float(params[0]) if len(params) > 0 else 1.0
                app_params['loc'] = float(params[1]) if len(params) > 1 else 0.0
                app_params['scale'] = float(params[2]) if len(params) > 2 else 1.0
            
            return app_params
            
        except Exception as e:
            logger.error(f"Error converting parameters for {dist_name}: {str(e)}")
            return {'mean': 10.0, 'std': 2.0, 'min_value': 0.0, 'max_value': 100.0, 'mean_value': 10.0}

    def _convert_prosit_to_app_format(self, prosit_params, net=None):
        """Convert ProSiT parameters to our application's format"""
        try:
            logger.info("Converting ProSiT parameters to application format...")
            
            # Access ProSiT parameters directly (not through to_dict())
            # Get transition weights - convert transition objects to names
            transition_weights = {}
            if hasattr(prosit_params, 'transition_weights'):
                for transition, weight in prosit_params.transition_weights.items():
                    if hasattr(transition, 'label') and transition.label:
                        transition_weights[transition.label] = float(weight)
                    elif hasattr(transition, 'name'):
                        transition_weights[transition.name] = float(weight)
            
            # Get execution time distributions from ProSiT parameters
            execution_time_params = {}
            exec_time_dists = getattr(prosit_params, 'execution_time_distributions', {})
            logger.info(f"Found execution time distributions for {len(exec_time_dists)} activities")
            
            # Debug: Check the actual structure of execution_time_distributions
            if exec_time_dists:
                logger.info(f"Sample execution time entry: {list(exec_time_dists.items())[0] if exec_time_dists else 'None'}")
            
            for activity, dist_info in exec_time_dists.items():
                logger.info(f"Processing execution time for activity: {activity}, dist_info type: {type(dist_info)}")
                if isinstance(dist_info, dict):
                    params = dist_info.get('params', [10.0, 2.0])
                    execution_time_params[activity] = {
                        'distribution': dist_info.get('dist_name', 'norm'),
                        'parameters': {
                            'params': params,
                            'min_value': dist_info.get('min_value', 1.0),
                            'max_value': dist_info.get('max_value', 100.0),
                            'mean_value': params[0] if params and len(params) > 0 else 10.0
                        }
                    }
                    logger.info(f"Activity {activity}: {dist_info.get('dist_name', 'norm')} with params {params}")
                elif isinstance(dist_info, tuple) and len(dist_info) >= 5:
                    # Handle ProSiT tuple format: (distribution_obj, params, min, max, mean)
                    distribution_obj, params, min_val, max_val, mean_val = dist_info[:5]
                    # Extract distribution name from scipy object
                    dist_name = 'norm'  # default
                    if hasattr(distribution_obj, 'name'):
                        dist_name = distribution_obj.name
                    elif 'norm' in str(distribution_obj):
                        dist_name = 'norm'
                    elif 'expon' in str(distribution_obj):
                        dist_name = 'expon'
                    elif 'lognorm' in str(distribution_obj):
                        dist_name = 'lognorm'
                    
                    # Convert params to list if it's a tuple
                    param_list = list(params) if hasattr(params, '__iter__') else [float(params)]
                    
                    execution_time_params[activity] = {
                        'distribution': dist_name,
                        'parameters': {
                            'params': param_list,
                            'min_value': float(min_val),
                            'max_value': float(max_val),
                            'mean_value': float(mean_val)
                        }
                    }
                    logger.info(f"Activity {activity}: {dist_name} with params {param_list}, mean {mean_val}")
                elif dist_info is not None:
                    # Handle other non-dict formats
                    logger.info(f"Unknown execution time data format for {activity}: {dist_info}")
                    execution_time_params[activity] = {
                        'distribution': 'norm',
                        'parameters': {
                            'params': [10.0, 2.0],
                            'min_value': 1.0,
                            'max_value': 100.0,
                            'mean_value': 10.0
                        }
                    }
            
            # Get resources and activity-resource assignments
            resources = getattr(prosit_params, 'resources', [])
            act_resource_prob = getattr(prosit_params, 'act_resource_prob', {})
            multitasking_resources = getattr(prosit_params, 'multitasking_resources', [])
            
            # Convert activity-resource probabilities to resource weights and assignments
            resource_weights = {}
            act_to_resources = {}
            
            for resource in resources:
                # Calculate average weight across all activities
                total_weight = 0
                activity_count = 0
                for activity, res_probs in act_resource_prob.items():
                    if resource in res_probs:
                        total_weight += res_probs[resource]
                        activity_count += 1
                resource_weights[resource] = total_weight / activity_count if activity_count > 0 else 0.1
            
            # Create activity-to-resource assignments
            for activity, res_probs in act_resource_prob.items():
                assigned_resources = []
                for resource, prob in res_probs.items():
                    if prob > 0:  # Only include resources with non-zero probability
                        assigned_resources.append(resource)
                act_to_resources[activity] = assigned_resources
            
            # Get calendars and convert numeric day keys to day names
            prosit_calendars = getattr(prosit_params, 'calendars', {})
            logger.info(f"Found calendars for {len(prosit_calendars)} resources: {list(prosit_calendars.keys())}")
            
            # Convert ProSiT calendar format (numeric days) to expected format (day names)
            calendars = {}
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            
            for resource, resource_calendar in prosit_calendars.items():
                calendars[resource] = {}
                for day_idx, day_schedule in resource_calendar.items():
                    if str(day_idx).isdigit() and int(day_idx) < 7:
                        day_name = day_names[int(day_idx)]
                        calendars[resource][day_name] = day_schedule
                        
            logger.info(f"Converted calendars for {len(calendars)} resources with day names")
            
            # Get waiting time distributions (resource-specific)
            waiting_time_distributions = {}
            resource_waiting_times = {}
            wait_time_dists = getattr(prosit_params, 'waiting_time_distributions', {})
            logger.info(f"Found waiting time distributions for {len(wait_time_dists)} resources")
            
            for resource, dist_info in wait_time_dists.items():
                logger.info(f"Processing waiting time for resource: {resource}, dist_info type: {type(dist_info)}")
                if isinstance(dist_info, dict):
                    params = dist_info.get('params', [0.1])
                    resource_waiting_times[resource] = {
                        'distribution': dist_info.get('dist_name', 'expon'),
                        'parameters': {
                            'params': params,
                            'min_value': dist_info.get('min_value', 0.0),
                            'max_value': dist_info.get('max_value', 60.0),
                            'mean_value': params[0] if params and len(params) > 0 else 5.0
                        }
                    }
                    logger.info(f"Resource {resource}: {dist_info.get('dist_name', 'expon')} waiting time with params {params}")
                elif isinstance(dist_info, tuple) and len(dist_info) >= 5:
                    # Handle ProSiT tuple format: (distribution_obj, params, min, max, mean)
                    distribution_obj, params, min_val, max_val, mean_val = dist_info[:5]
                    # Extract distribution name from scipy object
                    dist_name = 'expon'  # default for waiting times
                    if hasattr(distribution_obj, 'name'):
                        dist_name = distribution_obj.name
                    elif 'expon' in str(distribution_obj):
                        dist_name = 'expon'
                    elif 'norm' in str(distribution_obj):
                        dist_name = 'norm'
                    elif 'lognorm' in str(distribution_obj):
                        dist_name = 'lognorm'
                    
                    # Convert params to list if it's a tuple
                    param_list = list(params) if hasattr(params, '__iter__') else [float(params)]
                    
                    resource_waiting_times[resource] = {
                        'distribution': dist_name,
                        'parameters': {
                            'params': param_list,
                            'min_value': float(min_val),
                            'max_value': float(max_val),
                            'mean_value': float(mean_val)
                        }
                    }
                    logger.info(f"Resource {resource}: {dist_name} waiting time with params {param_list}, mean {mean_val}")
                elif dist_info is not None:
                    # Handle other non-dict formats
                    logger.info(f"Unknown waiting time data format for {resource}: {dist_info}")
                    resource_waiting_times[resource] = {
                        'distribution': 'expon',
                        'parameters': {
                            'params': [5.0],
                            'min_value': 0.0,
                            'max_value': 60.0,
                            'mean_value': 5.0
                        }
                    }
            
            # Get arrival time parameters
            arrival_dist = getattr(prosit_params, 'arrival_time_distributions', {})
            arrival_calendar = getattr(prosit_params, 'arrival_calendar', {})
            
            inter_arrival_time = {}
            if isinstance(arrival_dist, dict):
                inter_arrival_time = {
                    'distribution': arrival_dist.get('dist_name', 'exponential'),
                    'parameters': {
                        'params': arrival_dist.get('params', [0.1]),
                        'min_value': arrival_dist.get('min_value', 1.0),
                        'max_value': arrival_dist.get('max_value', 100.0),
                        'mean_value': arrival_dist.get('params', [10.0])[0] if arrival_dist.get('params') else 10.0
                    },
                    'calendar': arrival_calendar
                }
            
            # Extract process model structure
            activities = []
            places = []
            transitions = []
            arcs = []
            svg_content = ""
            
            if net:
                activities = [t.label for t in net.transitions if t.label]
                places = [p.name for p in net.places]
                
                # Build transition structure for frontend
                for t in net.transitions:
                    if t.label:
                        transitions.append({
                            'id': t.name or t.label,
                            'name': t.label,
                            'label': t.label
                        })
                
                # Build arc structure
                for arc in net.arcs:
                    arcs.append({
                        'source': arc.source.name or str(arc.source),
                        'target': arc.target.name or str(arc.target),
                        'weight': getattr(arc, 'weight', 1)
                    })
                
                # Generate SVG content if possible
                try:
                    from pm4py.visualization.petri_net import visualizer as pn_visualizer
                    gviz = pn_visualizer.apply(net, parameters={"format": "svg"})
                    svg_content = str(gviz)
                except:
                    svg_content = ""
            
            # Build the final parameters structure
            parameters = {
                'process_model': {
                    'activities': activities,
                    'places': places,
                    'transitions': transitions,
                    'arcs': arcs,
                    'svg_content': svg_content
                },
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
                    'act_resource_prob': act_resource_prob,
                    'calendars': calendars
                },
                'waiting_time_params': {
                    'resource_waiting_times': resource_waiting_times
                },
                'inter_arrival_params': {
                    'inter_arrival_time': inter_arrival_time
                }
            }
            
            logger.info(f"Converted parameters: {len(resources)} resources, {len(execution_time_params)} activities with execution times, {len(multitasking_resources)} multitasking resources")
            logger.info(f"Activities with execution times: {list(execution_time_params.keys())}")
            logger.info(f"Resources with waiting times: {list(resource_waiting_times.keys())}")
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error converting ProSiT parameters: {str(e)}")
            logger.error(f"ProSiT params attributes: {dir(prosit_params)}")
            raise
    
    def import_pnml_model(self, pnml_file_path):
        """
        Import process model from PNML file using pm4py.read_pnml
        Returns: process model structure with extracted parameters
        """
        try:
            logger.info(f"Importing PNML model from {pnml_file_path}")
            
            # Import PNML file using PM4Py
            net, initial_marking, final_marking = pm4py.read_pnml(pnml_file_path)
            
            # Store the net and markings
            self.petri_net = net
            self.initial_marking = initial_marking
            self.final_marking = final_marking
            
            # Extract activities from the net and create transition mappings
            activities = []
            transitions = []
            places = []
            arcs = []
            self.transition_mappings = {}
            
            for transition in net.transitions:
                if transition.label:  # Skip silent transitions
                    transition_name = transition_to_name(transition)
                    activities.append(transition_name)
                    transitions.append({
                        'id': transition.name or transition.label,
                        'name': transition.label,
                        'label': transition.label
                    })
                    # Create bidirectional mapping
                    self.transition_mappings[transition_name] = transition
                    self.transition_mappings[transition.name] = transition
            
            for place in net.places:
                places.append(place.name)
            
            # Build arc structure
            for arc in net.arcs:
                arcs.append({
                    'source': arc.source.name or str(arc.source),
                    'target': arc.target.name or str(arc.target),
                    'weight': getattr(arc, 'weight', 1)
                })
            
            # Generate visualization
            svg_content = ""
            try:
                gviz = pn_visualizer.apply(net, initial_marking, final_marking, parameters={"format": "svg"})
                svg_content = str(gviz)
            except Exception as viz_e:
                logger.warning(f"Failed to generate visualization: {str(viz_e)}")
                svg_content = ""
            
            # Create process model structure
            process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'arcs': arcs,
                'svg_content': svg_content
            }
            
            logger.info(f"PNML model imported successfully: {len(activities)} activities, {len(places)} places")
            
            # Generate default parameters for imported model
            parameters = self._generate_default_parameters_for_pnml(process_model)
            
            return parameters
            
        except Exception as e:
            logger.error(f"Failed to import PNML model: {str(e)}")
            raise e
    
    def import_petri_net_from_pnml(self, pnml_file_path):
        """
        Import only the Petri net structure from PNML file for use with XES parameter discovery
        Returns: process model structure without parameters (parameters come from XES)
        """
        try:
            logger.info(f"Importing Petri net structure from {pnml_file_path}")
            
            # Import PNML file using PM4Py
            net, initial_marking, final_marking = pm4py.read_pnml(pnml_file_path)
            
            # Store the net and markings
            self.petri_net = net
            self.initial_marking = initial_marking
            self.final_marking = final_marking
            
            # Extract activities from the net and create transition mappings
            activities = []
            transitions = []
            places = []
            arcs = []
            self.transition_mappings = {}
            
            for transition in net.transitions:
                if transition.label:  # Skip silent transitions
                    transition_name = transition_to_name(transition)
                    activities.append(transition_name)
                    transitions.append({
                        'id': transition.name or transition.label,
                        'name': transition.label,
                        'label': transition.label
                    })
                    # Create bidirectional mapping
                    self.transition_mappings[transition_name] = transition
                    self.transition_mappings[transition.name] = transition
            
            for place in net.places:
                places.append(place.name)
            
            # Build arc structure
            for arc in net.arcs:
                arcs.append({
                    'source': arc.source.name or str(arc.source),
                    'target': arc.target.name or str(arc.target),
                    'weight': getattr(arc, 'weight', 1)
                })
            
            # Generate visualization
            svg_content = ""
            try:
                gviz = pn_visualizer.apply(net, initial_marking, final_marking, parameters={"format": "svg"})
                svg_content = str(gviz)
            except Exception as viz_e:
                logger.warning(f"Failed to generate visualization: {str(viz_e)}")
                svg_content = ""
            
            # Create process model structure (without parameters)
            process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'arcs': arcs,
                'svg_content': svg_content,
                'visualization': svg_content
            }
            
            logger.info(f"PNML Petri net imported successfully: {len(activities)} activities, {len(places)} places")
            
            return process_model
            
        except Exception as e:
            logger.error(f"Failed to import Petri net from PNML: {str(e)}")
            raise e
    
    def _generate_default_parameters_for_pnml(self, process_model):
        """Generate default simulation parameters for imported PNML model"""
        try:
            activities = process_model.get('activities', [])
            
            # Create default execution time parameters
            execution_time_params = {}
            for activity in activities:
                execution_time_params[activity] = {
                    'distribution': 'norm',
                    'parameters': {
                        'mean': 60.0,  # 60 minutes default
                        'std': 15.0,   # 15 minutes std dev
                        'min': 5.0,    # minimum 5 minutes
                        'max': 480.0   # maximum 8 hours
                    }
                }
            
            # Create default transition weights (equal probability)
            transition_weights = {}
            for transition in process_model.get('transitions', []):
                transition_weights[transition.get('id', '')] = 1.0
            
            # Create default resource assignments (single resource per activity)
            resource_assignments = {}
            default_resources = ['Resource_1', 'Resource_2', 'Resource_3', 'Resource_4']
            for i, activity in enumerate(activities):
                resource_assignments[activity] = [default_resources[i % len(default_resources)]]
            
            # Create default resource calendars (24/7 availability)
            resource_calendars = {}
            for resource in default_resources:
                resource_calendars[resource] = self._create_default_calendar()
            
            # Create default waiting time parameters
            waiting_time_params = {
                'resource_waiting_times': {}
            }
            for resource in default_resources:
                waiting_time_params['resource_waiting_times'][resource] = {
                    'distribution': 'expon',
                    'parameters': {
                        'scale': 30.0  # 30 minutes mean waiting time
                    }
                }
            
            # Create default inter-arrival parameters
            inter_arrival_params = {
                'inter_arrival_time': {
                    'distribution': 'expon',
                    'parameters': {
                        'scale': 60.0  # 60 minutes mean inter-arrival time
                    },
                    'calendar': self._create_default_calendar()
                }
            }
            
            parameters = {
                'process_model': process_model,
                'execution_time_params': execution_time_params,
                'transition_params': {
                    'transition_weights': transition_weights
                },
                'resource_params': {
                    'resources': default_resources,
                    'resource_weights': {res: 1.0 for res in default_resources},
                    'multitasking_resource': [],
                    'act_to_resources': resource_assignments,
                    'calendars': resource_calendars
                },
                'waiting_time_params': waiting_time_params,
                'inter_arrival_params': inter_arrival_params
            }
            
            logger.info(f"Generated default parameters for {len(activities)} activities")
            return parameters
            
        except Exception as e:
            logger.error(f"Failed to generate default parameters: {str(e)}")
            raise e
    
    def _create_default_calendar(self):
        """Create a default 24/7 calendar"""
        calendar = {}
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for day in days:
            calendar[day] = {str(hour): True for hour in range(24)}
        return calendar

    def _create_fallback_parameters(self, event_log, net, initial_marking, final_marking):
        """Create simplified parameters when ProSiT discovery fails"""
        try:
            logger.info("Creating fallback parameters...")
            
            # Initialize ProSiT parameters with basic structure
            self.prosit_params = SimulatorParameters(net, initial_marking, final_marking)
            
            # Set basic transition weights (equal probability)
            self.prosit_params.transition_weights = {}
            for transition in net.transitions:
                if transition.label:  # Skip silent transitions
                    self.prosit_params.transition_weights[transition] = 1.0
            
            # Set basic resources from event log if available
            resources = []
            try:
                if event_log and len(event_log) > 0:
                    for trace in event_log:
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
            
            self.prosit_params.resources = resources
            
            # Set basic resource-activity probabilities
            self.prosit_params.act_resource_prob = {}
            activities = [t.label for t in net.transitions if t.label]
            for activity in activities:
                self.prosit_params.act_resource_prob[activity] = {
                    resource: 1.0 / len(resources) for resource in resources
                }
            
            # Set basic execution time distributions (normal distribution)
            self.prosit_params.execution_time_distributions = {}
            for activity in activities:
                self.prosit_params.execution_time_distributions[activity] = {
                    'dist_name': 'normal',
                    'params': [10.0, 2.0],  # mean=10, std=2
                    'min_value': 1.0,
                    'max_value': 30.0
                }
            
            # Set basic waiting time distributions
            self.prosit_params.waiting_time_distributions = {}
            for resource in resources:
                self.prosit_params.waiting_time_distributions[resource] = {
                    'dist_name': 'exponential',
                    'params': [0.1],
                    'min_value': 0.0,
                    'max_value': 60.0
                }
            
            # Set basic calendars (24/7 availability)
            self.prosit_params.calendars = {}
            for resource in resources:
                calendar = {}
                days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                for day in days:
                    calendar[day] = {str(hour): True for hour in range(24)}
                self.prosit_params.calendars[resource] = calendar
            
            # Set basic arrival calendar
            self.prosit_params.arrival_calendar = {
                day: {str(hour): True for hour in range(24)} 
                for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            }
            
            # Set basic arrival time distribution
            self.prosit_params.arrival_time_distributions = {
                'dist_name': 'exponential',
                'params': [0.1],
                'min_value': 1.0,
                'max_value': 100.0
            }
            
            # Set multitasking resources (none by default)
            self.prosit_params.multitasking_resources = []
            
            logger.info(f"Created fallback parameters with {len(resources)} resources and {len(activities)} activities")
            
        except Exception as e:
            logger.error(f"Error creating fallback parameters: {str(e)}")
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
            enhanced_svg = self._enhance_svg_visualization(svg_content, net)
            
            return enhanced_svg
            
        except Exception as e:
            logger.error(f"Error generating visualization: {str(e)}")
            return None
    
    def _enhance_svg_visualization(self, svg_content, net):
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