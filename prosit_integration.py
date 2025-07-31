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
        self.supported_formats = ['.xes']
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
            
            # Debug: Check event log structure for ProSiT compatibility
            try:
                if event_log is not None and len(event_log) > 0:
                    first_trace = event_log[0]
                    if first_trace is not None and len(first_trace) > 0:
                        first_event = first_trace[0]
                        logger.info(f"Event log structure - First event type: {type(first_event)}")
                        if hasattr(first_event, 'keys'):
                            logger.info(f"Event log structure - First event keys: {list(first_event.keys())}")
                            if 'org:resource' in first_event:
                                logger.info(f"Resource attribute found: {first_event['org:resource']}")
                            else:
                                logger.warning("No 'org:resource' attribute found in first event")
                        else:
                            logger.info("Event log structure - Event has no keys method")
            except Exception as debug_error:
                logger.warning(f"Debug event log structure failed: {str(debug_error)}")
            
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
            parameters = self._convert_prosit_to_app_format(self.prosit_params)
            
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
            return self._convert_prosit_to_app_format(self.prosit_params)
            
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
    
    def _convert_prosit_to_app_format(self, prosit_params):
        """Convert ProSiT parameters to our application's format"""
        try:
            # Get the ProSiT parameter dictionary
            prosit_dict = prosit_params.to_dict()
            
            # Extract execution time parameters and convert to our format
            execution_time_params = {}
            prosit_exec_times = prosit_dict.get('execution_time_params', {}).get('execution_time_distributions', {})
            
            for activity, dist_info in prosit_exec_times.items():
                if isinstance(dist_info, dict):
                    execution_time_params[activity] = {
                        'distribution': dist_info.get('dist_name', 'normal'),
                        'parameters': {
                            'params': dist_info.get('params', []),
                            'min_value': dist_info.get('min_value', 0),
                            'max_value': dist_info.get('max_value', 100),
                            'mean_value': dist_info.get('mean_value', 50)
                        }
                    }
            
            # Extract arrival time parameters
            arrival_params = prosit_dict.get('arrival_params', {})
            arrival_dist = arrival_params.get('arrival_time_distributions', {})
            
            inter_arrival_time = {
                'distribution': arrival_dist.get('dist_name', 'exponential'),
                'parameters': {
                    'params': arrival_dist.get('params', [0.1]),
                    'min_value': arrival_dist.get('min_value', 1),
                    'max_value': arrival_dist.get('max_value', 100),
                    'mean_value': arrival_dist.get('mean_value', 10)
                },
                'calendar': arrival_params.get('arrival_calendar', {})
            }
            
            # Convert transition weights
            transition_weights = {}
            prosit_transitions = prosit_dict.get('transition_params', {}).get('transition_weights', {})
            for trans_name, weight in prosit_transitions.items():
                transition_weights[trans_name] = weight
            
            # Extract resource parameters
            resource_params = prosit_dict.get('resource_params', {})
            
            # Convert waiting time parameters
            waiting_time_distributions = {}
            prosit_waiting = prosit_dict.get('waiting_time_params', {}).get('waiting_time_distributions', {})
            for resource, dist_info in prosit_waiting.items():
                if isinstance(dist_info, dict):
                    waiting_time_distributions[resource] = {
                        'distribution': dist_info.get('dist_name', 'exponential'),
                        'parameters': {
                            'params': dist_info.get('params', [0.1]),
                            'min_value': dist_info.get('min_value', 1),
                            'max_value': dist_info.get('max_value', 60),
                            'mean_value': dist_info.get('mean_value', 5)
                        }
                    }
            
            # Return in our application's format
            parameters = {
                'transition_params': {
                    'transition_weights': transition_weights
                },
                'execution_time_params': execution_time_params,
                'resource_params': {
                    'resources': resource_params.get('resources', ['Resource_1']),
                    'resource_probabilities': resource_params.get('resource_probabilities', {}),
                    'calendars': resource_params.get('calendars', {})
                },
                'waiting_time_params': {
                    'inter_arrival_time': inter_arrival_time,
                    'waiting_time_distributions': waiting_time_distributions
                }
            }
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error converting ProSiT parameters: {str(e)}")
            raise
    
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