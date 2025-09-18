from collections import Counter

import pm4py
from pm4py.objects.log.obj import EventLog
from prosit.utils.distribution_utils import return_best_distribution
import numpy as np


def discover_attributes_distribution(log: EventLog, label_data_attributes: list, label_data_attributes_categorical: list) -> dict:

    observed_values = {l: [] for l in label_data_attributes}
    for trace in log:
         for l in label_data_attributes:
            observed_values[l].append(trace[0][l])

    data_attributes_distribution = dict()
    for l in label_data_attributes:
        if l in label_data_attributes_categorical:
            frequency = Counter(observed_values[l])
            total = len(observed_values[l])
            data_attributes_distribution[l] = {lst: count / total for lst, count in frequency.items()}
        else:
            dist, params = return_best_distribution(observed_values[l], dist_search = ['fixed', 'norm', 'expon', 'uniform'])
            min_value = np.min(observed_values[l])
            max_value = np.max(observed_values[l])
            mean_value = np.mean(observed_values[l])
            data_attributes_distribution[l] = (dist, params, min_value, max_value, mean_value)

    return data_attributes_distribution


def return_label_data_attributes(log: EventLog) -> tuple:

    standard_xes_columns = {"case:concept:name", "concept:name", "time:timestamp", "start:timestamp", "org:resource", "org:role"}
    
    df_log = pm4py.convert_to_dataframe(log)
    label_data_attributes = list(set(df_log.columns) - standard_xes_columns)
    label_data_attributes_categorical = []
    for l in label_data_attributes:
        if type(df_log[l].iloc[0]) == str:
            label_data_attributes_categorical.append(l)
    
    return label_data_attributes, label_data_attributes_categorical