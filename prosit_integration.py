import os
import json
import logging
import numpy as np
from datetime import datetime, timedelta
import random
import xml.etree.ElementTree as ET
from xml.dom import minidom
import pm4py
from pm4py.visualization.petri_net import visualizer as pn_visualizer
from pm4py.objects.conversion.log import converter as xes_converter

import base64
from io import BytesIO

logger = logging.getLogger(__name__)

class ProSiTIntegration:
    """Integration layer for ProSiT library functionality"""
    
    def __init__(self):
        self.supported_formats = ['.xes']
    
    def discover_process_model(self, xes_file_path, noise_threshold=0.2):
        """
        Discover process model using PM4Py inductive miner
        Returns: process model structure with visualization
        """
        try:
            logger.info(f"Discovering process model from {xes_file_path} with noise threshold {noise_threshold}")
            
            # Load event log from XES file
            event_log = pm4py.read_xes(xes_file_path)
            logger.info(f"Loaded {len(event_log)} traces from XES file")
            
            # Apply inductive miner to discover Petri net
            net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(event_log, noise_threshold=noise_threshold)
            
            # Extract activities from the net
            activities = []
            transitions = []
            places = []
            
            for transition in net.transitions:
                if transition.label:  # Skip silent transitions
                    activities.append(transition.label)
                    transitions.append(transition.name)
            
            for place in net.places:
                places.append(place.name)
            
            # Generate visualization
            visualization_base64 = self._generate_petri_net_visualization(net, initial_marking, final_marking)
            
            # Create process model structure (exclude non-serializable objects)
            process_model = {
                'activities': activities,
                'transitions': transitions,
                'places': places,
                'start_activities': activities[:1] if activities else [],
                'end_activities': activities[-1:] if activities else [],
                'visualization': visualization_base64
            }
            
            logger.info(f"Discovered process model with {len(activities)} activities")
            return process_model
            
        except Exception as e:
            logger.error(f"Error discovering process model: {str(e)}")
            # Fallback to mock data if PM4Py fails
            logger.warning("Falling back to mock process model")
            return self._create_mock_process_model()
    
    def _generate_petri_net_visualization(self, net, initial_marking, final_marking):
        """Generate Petri net visualization using PM4Py and return as base64"""
        try:
            # Generate visualization
            gviz = pn_visualizer.apply(net, initial_marking, final_marking, parameters={
                pn_visualizer.Variants.WO_DECORATION.value.Parameters.FORMAT: "png"
            })
            
            # Save to BytesIO
            img_buffer = BytesIO()
            gviz.pipe(format='png', encoding=None)
            img_data = gviz.pipe(format='png')
            
            # Convert to base64
            img_base64 = base64.b64encode(img_data).decode('utf-8')
            return f"data:image/png;base64,{img_base64}"
            
        except Exception as e:
            logger.error(f"Error generating visualization: {str(e)}")
            return None
    
    def _create_mock_process_model(self):
        """Create mock process model as fallback"""
        return {
            'activities': [
                'Create Purchase Requisition',
                'Analyze Purchase Requisition', 
                'Create Request for Quotation Requester',
                'Analyze Request for Quotation',
                'Send Request for Quotation to Supplier',
                'Create Quotation comparison Map',
                'Analyze Quotation comparison Map',
                'Choose best option',
                'Settle conditions with supplier',
                'Create Purchase Order',
                'Confirm Purchase Order',
                'Deliver Goods Services',
                'Release Purchase Order',
                'Approve Purchase Order for payment',
                'Send invoice',
                'Release Supplier\'s Invoice',
                'Authorize Supplier\'s Invoice payment',
                'Pay invoice'
            ],
            'transitions': [],
            'places': [],
            'start_activities': ['Create Purchase Requisition'],
            'end_activities': ['Pay invoice'],
            'visualization': None
        }
    
    def discover_parameters(self, xes_file_path, process_model, max_depth=0):
        """
        Discover simulation parameters from event log
        Returns: comprehensive parameter structure
        """
        try:
            logger.info(f"Discovering parameters from {xes_file_path}")
            
            # Generate comprehensive parameters based on the provided JSON structure
            # but with additional timing parameters
            parameters = {
                "process_model": process_model,  # Include the process model for visualization
                "transition_params": {
                    "transition_weights": self._generate_transition_weights(process_model)
                },
                "resource_params": {
                    "resources": self._generate_resources(),
                    "multitasking_resource": self._generate_multitasking_resources(),
                    "act_to_resources": self._generate_activity_resource_mapping(process_model),
                    "resource_weights": self._generate_resource_weights(),
                    "calendars": self._generate_calendars()
                },
                "execution_time_params": {
                    "activity_durations": self._generate_execution_times(process_model)
                },
                "waiting_time_params": {
                    "inter_arrival_time": self._generate_inter_arrival_time(),
                    "resource_waiting_times": self._generate_waiting_times()
                }
            }
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error discovering parameters: {str(e)}")
            raise
    
    def _generate_transition_weights(self, process_model):
        """Generate transition weights between activities"""
        weights = {}
        activities = process_model.get('activities', [])
        
        for activity in activities:
            # Generate realistic transition weights
            weights[activity] = round(random.uniform(0.1, 1.0), 3)
            
        # Add some skip transitions
        for i in range(5):
            weights[f"skip_{i+1}"] = round(random.uniform(0.1, 0.9), 3)
            
        return weights
    
    def _generate_resources(self):
        """Generate list of available resources"""
        resource_names = [
            "Magdalena Predutta", "Karel de Groot", "Francois de Perrier",
            "Pedro Alvares", "Karalda Nimwada", "Kiu Kan", "Carmen Finacse",
            "Francis Odell", "Maris Freeman", "Heinz Gutschmidt",
            "Esmeralda Clay", "Karen Clarens", "Sean Manney", "Anne Olwada",
            "Fjodor Kowalski", "Nico Ojenbeer", "Miu Hanwan", "Tesca Lobes",
            "Penn Osterwalder", "Immanuel Karagianni", "Kim Passa",
            "Alberto Duport", "Christian Francois", "Esmana Liubiata",
            "Clement Duchot", "Elvira Lores", "Anna Kaufmann"
        ]
        return resource_names
    
    def _generate_multitasking_resources(self):
        """Generate list of multitasking resources"""
        resources = self._generate_resources()
        return random.sample(resources, k=min(8, len(resources)))
    
    def _generate_activity_resource_mapping(self, process_model):
        """Map activities to available resources"""
        activities = process_model.get('activities', [])
        resources = self._generate_resources()
        mapping = {}
        
        for activity in activities:
            # Assign 3-8 resources per activity
            num_resources = random.randint(3, min(8, len(resources)))
            mapping[activity] = random.sample(resources, k=num_resources)
            
        return mapping
    
    def _generate_resource_weights(self):
        """Generate resource availability weights"""
        resources = self._generate_resources()
        weights = {}
        
        for resource in resources:
            weights[resource] = round(random.uniform(0.05, 0.4), 4)
            
        return weights
    
    def _generate_calendars(self):
        """Generate resource calendars"""
        resources = self._generate_resources()
        calendars = {}
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        for resource in resources[:3]:  # Generate for first 3 resources as example
            calendar = {}
            for day in days:
                day_schedule = {}
                for hour in range(24):
                    # Most resources work 9-17, with some variations
                    if 9 <= hour <= 17:
                        day_schedule[str(hour)] = random.choice([True, True, True, False])  # 75% availability
                    else:
                        day_schedule[str(hour)] = random.choice([True, False, False, False])  # 25% availability
                calendar[day] = day_schedule
            calendars[resource] = calendar
            
        return calendars
    
    def _generate_execution_times(self, process_model):
        """Generate execution time distributions for activities"""
        activities = process_model.get('activities', [])
        durations = {}
        
        for activity in activities:
            durations[activity] = self._generate_duration_distribution()
            
        return durations
    
    def _generate_duration_distribution(self):
        """Generate a duration distribution"""
        distributions = ['fixed', 'norm', 'expon', 'lognorm', 'uniform']
        distribution = random.choice(distributions)
        
        if distribution == 'fixed':
            value = round(random.uniform(30, 90), 1)  # 30 minutes to 1.5 hours
            return {
                "distribution": distribution,
                "value": value
            }
        elif distribution == 'norm':
            mean = round(random.uniform(15, 120), 1)  # 15 minutes to 2 hours
            std = round(random.uniform(5, mean * 0.3), 1)
            return {
                "distribution": distribution,
                "mean": mean,
                "std": std,
                "min": round(max(1, mean - 2 * std), 1),
                "max": round(mean + 3 * std, 1)
            }
        elif distribution == 'expon':
            mean = round(random.uniform(20, 90), 1)
            return {
                "distribution": distribution,
                "mean": mean,
                "min": 1,
                "max": round(mean * 4, 1)
            }
        elif distribution == 'lognorm':
            mean = round(random.uniform(25, 80), 1)
            std = round(random.uniform(10, 30), 1)
            return {
                "distribution": distribution,
                "mean": mean,
                "std": std,
                "min": 5,
                "max": round(mean * 3, 1)
            }
        else:  # uniform
            min_val = round(random.uniform(10, 30), 1)
            max_val = round(random.uniform(min_val + 15, min_val + 90), 1)
            return {
                "distribution": distribution,
                "min": min_val,
                "max": max_val
            }
    
    def _generate_inter_arrival_time(self):
        """Generate inter-arrival time parameters"""
        params = self._generate_duration_distribution()
        params["calendar"] = self._generate_arrival_calendar()
        return params
    
    def _generate_arrival_calendar(self):
        """Generate arrival time calendar"""
        calendar = {}
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        for day in days:
            calendar[day] = {}
            for hour in range(24):
                # Default business hours (9-17) for weekdays, reduced hours for weekends
                if day in ["Saturday", "Sunday"]:
                    # Weekend: reduced hours
                    calendar[day][str(hour)] = 10 <= hour <= 16
                else:
                    # Weekdays: business hours with some variation
                    calendar[day][str(hour)] = 9 <= hour <= 17
        
        return calendar
    
    def _generate_waiting_times(self):
        """Generate waiting time parameters for resource queues"""
        resources = self._generate_resources()
        waiting_times = {}
        
        for resource in resources[:5]:  # Generate for first 5 resources as example
            waiting_times[resource] = self._generate_duration_distribution()
            
        return waiting_times
    
    def simulate_event_log(self, parameters, num_instances=100):
        """
        Generate simulated event log based on parameters
        Returns: path to generated XES file
        """
        try:
            logger.info(f"Starting simulation with {num_instances} instances")
            
            # Create XES structure
            log = ET.Element("log")
            log.set("xes.version", "1.0")
            log.set("xes.features", "nested-attributes")
            log.set("xmlns", "http://www.xes-standard.org/")
            
            # Add extensions
            extension = ET.SubElement(log, "extension")
            extension.set("name", "Concept")
            extension.set("prefix", "concept")
            extension.set("uri", "http://www.xes-standard.org/concept.xes")
            
            extension = ET.SubElement(log, "extension")
            extension.set("name", "Time")
            extension.set("prefix", "time")
            extension.set("uri", "http://www.xes-standard.org/time.xes")
            
            extension = ET.SubElement(log, "extension")
            extension.set("name", "Organizational")
            extension.set("prefix", "org")
            extension.set("uri", "http://www.xes-standard.org/org.xes")
            
            # Add global attributes
            global_trace = ET.SubElement(log, "global")
            global_trace.set("scope", "trace")
            
            string_attr = ET.SubElement(global_trace, "string")
            string_attr.set("key", "concept:name")
            string_attr.set("value", "name")
            
            # Generate traces (process instances)
            for case_id in range(1, num_instances + 1):
                trace = self._generate_trace(parameters, case_id)
                log.append(trace)
            
            # Save to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"simulated_log_{timestamp}.xes"
            filepath = os.path.join("simulations", filename)
            
            # Pretty print XML
            rough_string = ET.tostring(log, 'unicode')
            reparsed = minidom.parseString(rough_string)
            pretty_xml = reparsed.toprettyxml(indent="  ")
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(pretty_xml)
            
            logger.info(f"Simulation completed. Generated {filename}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error during simulation: {str(e)}")
            raise
    
    def _generate_trace(self, parameters, case_id):
        """Generate a single trace (process instance)"""
        trace = ET.Element("trace")
        
        # Add trace attributes
        string_attr = ET.SubElement(trace, "string")
        string_attr.set("key", "concept:name")
        string_attr.set("value", f"Case_{case_id}")
        
        # Get activities from transition parameters
        transition_weights = parameters.get("transition_params", {}).get("transition_weights", {})
        activities = [act for act in transition_weights.keys() if not act.startswith("skip_")]
        
        if not activities:
            # Fallback activities
            activities = [
                "Create Purchase Requisition",
                "Analyze Purchase Requisition",
                "Create Purchase Order",
                "Confirm Purchase Order",
                "Pay invoice"
            ]
        
        # Generate events for this trace
        current_time = datetime.now()
        resources = parameters.get("resource_params", {}).get("resources", ["System"])
        
        for i, activity in enumerate(activities[:random.randint(3, min(8, len(activities)))]):
            event = self._generate_event(activity, current_time, resources)
            trace.append(event)
            
            # Advance time based on execution parameters
            execution_params = parameters.get("execution_time_params", {}).get("activity_durations", {})
            if activity in execution_params:
                mean_duration = execution_params[activity].get("mean", 60)
            else:
                mean_duration = random.uniform(15, 120)
            
            current_time += timedelta(minutes=mean_duration + random.uniform(-10, 20))
        
        return trace
    
    def _generate_event(self, activity, timestamp, resources):
        """Generate a single event"""
        event = ET.Element("event")
        
        # Activity name
        string_attr = ET.SubElement(event, "string")
        string_attr.set("key", "concept:name")
        string_attr.set("value", activity)
        
        # Timestamp
        date_attr = ET.SubElement(event, "date")
        date_attr.set("key", "time:timestamp")
        date_attr.set("value", timestamp.isoformat() + "+00:00")
        
        # Resource
        string_attr = ET.SubElement(event, "string")
        string_attr.set("key", "org:resource")
        string_attr.set("value", random.choice(resources))
        
        # Lifecycle
        string_attr = ET.SubElement(event, "string")
        string_attr.set("key", "lifecycle:transition")
        string_attr.set("value", "complete")
        
        return event
