import pm4py
import pandas as pd
from pm4py.objects.log.obj import EventLog


def discover_resources_list(log: EventLog, thr: float = 0.95) -> list:

    resource_counts = pd.Series(pm4py.get_event_attribute_values(log, 'org:resource'))
    resource_counts = resource_counts / resource_counts.sum()
    resource_counts = resource_counts.sort_values(ascending=False)
    resource_counts_cumsum = resource_counts.cumsum()
    resource_counts = resource_counts[resource_counts_cumsum <= thr]
    resources = resource_counts.index.tolist()

    return resources


def discover_resource_acts_prob(log, resources) -> dict:

    act_resources = dict()
    for trace in log:
        for event in trace:
            res = event['org:resource']
            act = event['concept:name']
            if act not in act_resources.keys():
                act_resources[act] = {r: 0 for r in resources}
            if res not in resources:
                continue
            act_resources[act][res] += 1

    normalized = {}
    for act, res_dict in act_resources.items():
        total = sum(res_dict.values())
        if total == 0:
            normalized[act] = {res: 1/len(resources) for res in res_dict}
        else:
            normalized[act] = {res: val / total for res, val in res_dict.items()}

    for act in list(normalized.keys()):
        normalized[act] = {res: prob for res, prob in normalized[act].items() if prob > 0}

    return normalized


def discover_resources_per_act(log: EventLog, activities: list, resources: list, thr: float = 1.0) -> dict:

    df_log = pm4py.convert_to_dataframe(log)
    df_log = df_log[df_log["concept:name"].isin(activities)]
    df_log = df_log[df_log["org:resource"].isin(resources)]

    R_act = dict()
    for act in activities:
        df_log_act = df_log[df_log["concept:name"] == act]
        res_counts_act = df_log_act["org:resource"].value_counts()
        res_counts_act = res_counts_act / res_counts_act.sum()
        res_counts_act = res_counts_act.sort_values(ascending=False)
        res_counts_act_cumsum = res_counts_act.cumsum()
        res_counts_act = res_counts_act[res_counts_act_cumsum <= thr]
        resources_act = res_counts_act.index.tolist()
        R_act[act] = resources_act

    return R_act


def return_multitasking_resources(df_features: pd.DataFrame, thr = 0.05) -> list:
    
    def condition(group):
        total = len(group)
        positive = (group['res_workload'] > 0).sum()
        return (positive / total) >= thr

    filtered = df_features.groupby('resource').filter(condition)

    return filtered['resource'].unique().tolist()


def discover_weight_resources(
        df_features: pd.DataFrame,
        resources: list,
    ) -> dict :

    df_features = df_features[~df_features["resource"].isna()]

    weights_r = {r: (df_features["resource"] == r).sum() / df_features["prev_enabled_resources"].apply(lambda r_set: r in r_set).sum() for r in resources}

    return weights_r