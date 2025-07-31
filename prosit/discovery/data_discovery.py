from collections import Counter

import pm4py
from pm4py.objects.log.obj import EventLog


def discover_attributes_distribution(log: EventLog, label_data_attributes: list) -> dict:

    list_data_attributes = []
    for trace in log:
        list_data_attributes.append([trace[0][a] for a in label_data_attributes])

    list_data_attributes = [tuple(lst) for lst in list_data_attributes]
    frequency = Counter(list_data_attributes)
    total = len(list_data_attributes)
    data_attributes_distribution = {lst: count / total for lst, count in frequency.items()}

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