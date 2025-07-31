import re
from prosit.utils.distribution_utils import sampling_from_dist
from sklearn.tree import export_graphviz
import graphviz
import random
import numpy as np
import pandas as pd
import scipy.stats as stats

def build_graph_vis(model_t, model_distributions=False):

    try:
        dot_data = export_graphviz(model_t, 
                feature_names=model_t.feature_names_in_,
                label='none',
                filled=True, 
                rounded=True,
                impurity=False,
                proportion=True)
    except:
        dot_data = export_graphviz(model_t, 
                feature_names=model_t.feature_names_in_,
                label='none',
                rounded=True,
                impurity=False,
                proportion=True)

    new_dot_data = reformat_dot_str(dot_data, model_distributions)
    graph = graphviz.Source(new_dot_data)

    return graph


def reformat_dot_str(input_str, dot_distributions=False):

    result = re.sub(r'\d+\.?\d*\s?%\\n', '', input_str)
    result = re.sub(r'\[\d+\.?\d*,\s*(\d+\.?\d*)\]', r'\1', result)

    if dot_distributions:
        pattern = r'\[\[(\d+\.?\d*)\]\\n\[(\d+\.?\d*)\]\]'
            
        def round_and_replace(match):
            num1, num2 = match.groups()
            rounded1 = round(float(num1))
            rounded2 = round(float(num2))
            return f'({rounded1}, {rounded2})'
            
        result = re.sub(pattern, round_and_replace, result)
        
    return result


def parse_tree(dot_string):
    node_pattern = r'(\d+) \[label="([^"]+)"'
    edge_pattern = r'(\d+) -> (\d+)(?: \[labeldistance=[^,]+, labelangle=[^,]+, headlabel="([^"]+)"\])?'

    nodes = {}
    edges = []

    for match in re.findall(node_pattern, dot_string):
        node_id = int(match[0])
        label_info = match[1].split("\\n")
        if len(label_info) > 1:
            feature, threshold = label_info[0].split(" <= ")
            threshold = float(threshold)
            nodes[node_id] = {'feature': feature, 'threshold': threshold}
        else:
            try:
                nodes[node_id] = {'value': float(label_info[0])}  # Leaf node with a value
            except:
                nodes[node_id] = {'value': (int(label_info[0][1:-1].split(', ')[0]), int(label_info[0][1:-1].split(', ')[1]))}
    for match in re.findall(edge_pattern, dot_string):
        parent, child = int(match[0]), int(match[1])
        edges.append((parent, child))

    return nodes, edges


def build_tree_structure(nodes, edges):
    tree = {}

    def add_edge(parent, child, edge_index):
        if 'children' not in nodes[parent]:
            nodes[parent]['children'] = {}
        condition = (edge_index == 0)  # True for left (first edge), False for right (second edge)
        nodes[parent]['children'][condition] = child

    parent_edge_count = {}
    for parent, child in edges:
        if parent not in parent_edge_count:
            parent_edge_count[parent] = 0
        add_edge(parent, child, parent_edge_count[parent])
        parent_edge_count[parent] += 1

    return nodes


def traverse_tree(tree, features):
    
    if type(tree) != dict:
        return tree
    
    current_node = 0 
    while 'value' not in tree[current_node]:
        feature = tree[current_node]['feature']
        threshold = tree[current_node]['threshold']
        if features[feature] <= threshold:
            current_node = tree[current_node]['children'][True]
        else:
            current_node = tree[current_node]['children'][False]

    return tree[current_node]['value']

def traverse_tree_distribution(tree, features):

    if type(tree) != dict:
        return random.choice(tree)

    current_node = 0 
    while 'value' not in tree[current_node]:
        feature = tree[current_node]['feature']
        threshold = tree[current_node]['threshold']
        if features[feature] <= threshold:
            current_node = tree[current_node]['children'][True]
        else:
            current_node = tree[current_node]['children'][False]

    return random.choice(tree[current_node]['sampled'])


def transform_river_decision_tree_data(decision_tree, distribution=True, min_value=0, max_value=60*24) -> dict:

    if decision_tree.height == 0:
        if distribution:
            return {0: {'value': 0, 'sampled': [0], 'dist': ("fixed", (0,), 0, 0)}}
        else:
            return {0: {"value": 1}}

    df = decision_tree.to_dataframe()
    if df is None:
        if distribution:
            mean_var = decision_tree.debug_one({})
            pred_split = mean_var.split("\n")[-2].split(" | ")
            value = float(pred_split[0][6:].replace(",", ""))
            variance = float(pred_split[1][5:].replace(",", ""))
            # Calculate standard deviation, ensuring variance is non-negative
            std_dev = np.sqrt(max(0, variance))
            
            if std_dev == 0:
                sampled_values = [value]
            else:
                # Sample 100 values from a normal distribution
                sampled_values = np.random.normal(loc=value, scale=std_dev, size=1000)
                sampled_values[sampled_values < min_value] = value
                sampled_values[sampled_values > max_value] = value
                sampled_values = sampled_values.tolist()

            return {0: {'value': value, 'sampled': sampled_values, 'dist': (getattr(stats, "norm"), (value, std_dev), min_value, max_value)}}
        else:
            value = decision_tree.predict_proba_one({})[1]
            return {0: {"value": value}}

    transformed_data = {}

    # Iterate over each row in the DataFrame to process nodes
    # Use row.name to get the index (which is the node ID)
    for node_id, row in df.iterrows():
        is_leaf = row['is_leaf']

        # Check if it's a decision node based on 'is_leaf' and presence of 'feature'/'threshold'
        if not is_leaf and pd.notna(row['feature']) and pd.notna(row['threshold']):
            feature = row['feature']
            threshold = row['threshold']

            # Find immediate children nodes by filtering the DataFrame
            # Children are identified by having the current node's ID as their 'parent'
            children_nodes_df = df[df['parent'] == node_id].sort_values(df.index.name if df.index.name else df.index.values[0]) # Adjusted for index as node ID
            children_node_ids = children_nodes_df.index.tolist() # Get index values as children IDs

            children_dict = {}
            # Assuming a binary tree structure, assign children based on their node IDs
            # The smaller node ID is typically associated with the 'False' branch, larger with 'True'
            if len(children_node_ids) == 2:
                children_dict[False] = int(children_node_ids[0])
                children_dict[True] = int(children_node_ids[1])
            elif len(children_node_ids) == 1:
                # If only one child, assign it to 'True' as a default assumption
                children_dict[True] = int(children_node_ids[0])
            # If no children are found, children_dict remains empty

            transformed_data[node_id] = {
                'feature': feature,
                'threshold': threshold,
                'children': children_dict
            }
        else:
            # This is a leaf node (or a node that cannot be a decision node due to missing data)
            # Assign a default 'value' for leaf nodes as it's not present in the dataset
            
            if distribution:
                value = row['stats'].mean.get()
                variance = row['stats'].get()

                # Calculate standard deviation, ensuring variance is non-negative
                std_dev = np.sqrt(max(0, variance))
                
                if std_dev == 0:
                    sampled_values = [value]
                else:
                    # Sample 100 values from a normal distribution
                    sampled_values = np.random.normal(loc=value, scale=std_dev, size=max(1000, int(row['stats'].n)))
                    sampled_values[sampled_values < min_value] = value
                    sampled_values[sampled_values > max_value] = value
                    sampled_values = sampled_values.tolist()

                transformed_data[node_id] = {
                    'value': value,
                    'sampled': sampled_values,
                    'dist': (getattr(stats, "norm"), (value, std_dev), min_value, max_value)
                }
            else:
                value = row['stats'][1]/(row['stats'][0]+row['stats'][1])
                transformed_data[node_id] = {'value': value}

    # Sort the dictionary by node IDs for consistent output
    transformed_data_sorted = dict(sorted(transformed_data.items()))
    return transformed_data_sorted


class DecisionRules:
    def __init__(self):
        self.rules = None
        self.graph = None

    def from_decision_tree(self, decision_tree):
        self.decision_tree = decision_tree
        self.graph = build_graph_vis(decision_tree, True)
        nodes, edges = parse_tree(self.graph.source)
        self.rules = build_tree_structure(nodes, edges)

    def from_river_decision_tree(self, decision_tree, distribution=False, min_value=0, max_value=60*24):
        self.decision_tree = decision_tree
        self.rules = transform_river_decision_tree_data(decision_tree, distribution, min_value, max_value)

    def from_dict(self, dict_value):
        if type(dict_value) == float:
            self.rules = dict_value
        else:
            self.rules = sampling_from_dist(dict_value[0], dict_value[1], dict_value[2], dict_value[3], dict_value[1])

    def apply(self, features):
        return traverse_tree(self.rules, features)
    
    def apply_distribution(self, features):
        return traverse_tree_distribution(self.rules, features)
    
    def write_dot(self, file_name='decision_tree.dot'):
        if self.graph:
            self.graph.render(file_name)