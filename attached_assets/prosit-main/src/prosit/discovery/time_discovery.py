import numpy as np
from tqdm import tqdm
import pandas as pd
import pm4py

from sklearn.tree import DecisionTreeRegressor
from sklearn.model_selection import GridSearchCV

from pm4py.objects.log.obj import EventLog

from prosit.utils.common_utils import count_false_hours
from prosit.utils.distribution_utils import return_best_distribution, sampling_from_dist, remove_outliers
from prosit.utils.rule_utils import DecisionRules


DIST_SEARCH = ['fixed', 'norm', 'expon', 'lognorm', 'uniform']


# DISCOVERY

def discover_arrival_time(
        log: EventLog, 
        calendar_arrival: dict, 
        max_depths: list = range(1,6)
    ) -> DecisionRules:

    if not max_depths:
        arrival_time_distr = find_best_distribution_arrival(log, calendar_arrival)
    else:
        arrival_time_distr = build_model_arrival(log, calendar_arrival, max_depths)

    return arrival_time_distr



def discover_execution_time_distributions(
        df_features: pd.DataFrame, 
        net_transition_labels: list,
        resources: list, 
        calendars: dict, 
        max_depths: list = range(1,6),
        label_data_attributes: list = [], 
        label_data_attributes_categorical: list = [], 
        values_categorical: dict = dict(),
    ) -> dict:

    if not max_depths:
        activity_exec_time_distributions = find_best_distribution_ex(df_features, net_transition_labels, calendars)
    else:
        activity_exec_time_distributions = build_models_ex(
                                                            df_features, 
                                                            net_transition_labels,
                                                            resources,
                                                            calendars,
                                                            label_data_attributes, 
                                                            label_data_attributes_categorical, 
                                                            values_categorical, 
                                                            max_depths
                                                        )

    return activity_exec_time_distributions



def discover_waiting_time(
        df_features: pd.DataFrame,
        net_transition_labels: list, 
        resources: list,
        calendars: dict, 
        label_data_attributes: list, 
        label_data_attributes_categorical: list, 
        values_categorical: dict, 
        max_depths: list = range(1,6)
    ) -> dict:

    if not max_depths:
        res_waiting_time_distributions = find_best_distribution_wt(df_features, resources, calendars)
    else:
        res_waiting_time_distributions = build_models_wt(
                                                            df_features, 
                                                            net_transition_labels,
                                                            resources,
                                                            calendars, 
                                                            label_data_attributes, 
                                                            label_data_attributes_categorical, 
                                                            values_categorical, 
                                                            max_depths
                                                        )

    return res_waiting_time_distributions



# BUILD ML MODELS

def build_model_arrival(
        log: EventLog, 
        calendar_arrival: dict, 
        max_depths: list = range(1,6)
    ) -> DecisionRules:

    param_grid = {'max_depth': max_depths}

    df = build_training_df_arrival(log, calendar_arrival)

    X = df.drop(columns=['arrival_time'])
    y = df['arrival_time']

    if len(X) == 0:
        clf = DecisionRules()
        clf.rules = {0: {'value': 0.0, 'sampled':[0], 'dist': ('fixed', (0,))}}
        return clf

    if max_depths:
        if len(X)>3:
            clf_mean = DecisionTreeRegressor(random_state=72)
            grid_search = GridSearchCV(estimator=clf_mean, param_grid=param_grid, cv=3).fit(X, y)
            clf_mean = grid_search.best_estimator_
        else:
            clf_mean = DecisionTreeRegressor(max_depth=1, random_state=72).fit(X, y)
    else:
        clf_mean = DecisionTreeRegressor(random_state=72, max_depth=5)
        clf_mean.fit(X, y)


    leaf_indices = clf_mean.apply(X)

    y_leaf = pd.DataFrame({
        'Leaf': leaf_indices,
        'Y': y
    })

    clf = DecisionRules()
    clf.from_decision_tree(clf_mean)

    leaves = list(y_leaf['Leaf'].unique())
    for l in leaves:
        y = y_leaf[y_leaf['Leaf']==l]['Y']
        y = remove_outliers(y)
        min_value = np.min(y)
        max_value = np.max(y)
        dist, params = return_best_distribution(y, dist_search=DIST_SEARCH)
        sampled = sampling_from_dist(dist, params, min_value, max_value, clf.rules[l]['value'], n_sample=max(len(y), 1000))
        clf.rules[l]['dist'] = dist, params, min_value, max_value
        clf.rules[l]['sampled'] = list(sampled)

    return clf



def build_models_ex(
        df_features: pd.DataFrame, 
        activity_labels: list,
        resources: list,
        calendars: dict,
        label_data_attributes: list, 
        label_data_attributes_categorical: list, 
        values_categorical: dict, 
        max_depths: list = range(1,6)
    ) -> dict:

    df = build_training_df_ex(
                                df_features,
                                resources, 
                                activity_labels, 
                                calendars,
                                label_data_attributes, 
                                label_data_attributes_categorical, 
                                values_categorical
                            )
    
    param_grid = {'max_depth': max_depths}

    models_act = dict()
    
    for act in tqdm(activity_labels):

        df_act = df[df['activity_executed'] == act].iloc[:,1:]

        X = df_act.drop(columns=['execution_time'])
        y = df_act['execution_time']

        if len(X) == 0:
            clf = DecisionRules()
            clf.rules = {0: {'value': 0.0, 'sampled':[0], 'dist': ('fixed', (0,))}}
            models_act[act] = clf
            continue

        if max_depths:
            if len(X)>3:
                clf_mean = DecisionTreeRegressor(random_state=72)
                grid_search = GridSearchCV(estimator=clf_mean, param_grid=param_grid, cv=3).fit(X, y)
                clf_mean = grid_search.best_estimator_
            else:
                clf_mean = DecisionTreeRegressor(max_depth=1, random_state=72).fit(X, y)
        else:
            clf_mean = DecisionTreeRegressor(random_state=72, max_depth=5)
            clf_mean.fit(X, y)

        leaf_indices = clf_mean.apply(X)

        y_leaf = pd.DataFrame({
            'Leaf': leaf_indices,
            'Y': y
        })

        clf = DecisionRules()
        clf.from_decision_tree(clf_mean)

        leaves = list(y_leaf['Leaf'].unique())
        for l in leaves:
            y = y_leaf[y_leaf['Leaf']==l]['Y']
            y = remove_outliers(y)
            min_value = np.min(y)
            max_value = np.max(y)
            dist, params = return_best_distribution(y, dist_search=DIST_SEARCH)
            sampled = sampling_from_dist(dist, params, min_value, max_value, clf.rules[l]["value"], n_sample=max(len(y), 1000))
            clf.rules[l]['dist'] = dist, params, min_value, max_value
            clf.rules[l]['sampled'] = list(sampled)

        models_act[act] = clf

    return models_act



def build_models_wt(
        df_features: pd.DataFrame, 
        activity_labels: list,
        resources: list,
        calendars: dict, 
        label_data_attributes: list, 
        label_data_attributes_categorical: list, 
        values_categorical: dict, 
        max_depths: list = range(1,6)
    ) -> dict:

    df = build_training_df_wt(
                                df_features,
                                activity_labels,
                                calendars, 
                                label_data_attributes,
                                label_data_attributes_categorical,
                                values_categorical
                            )       

    param_grid = {'max_depth': max_depths}

    models_res = dict()
    for res in tqdm(resources):
        df_res = df[df['resource'] == res].iloc[:,1:]

        X = df_res.drop(columns=['waiting_time'])
        y = df_res['waiting_time']

        if len(X) == 0:
            clf = DecisionRules()
            clf.rules = {0: {'value': 0.0, 'sampled':[0], 'dist': ('fixed', (0,))}}
            models_res[res] = clf
            continue

        if max_depths:
            if len(X)>3:
                clf_mean = DecisionTreeRegressor(random_state=72)
                grid_search = GridSearchCV(estimator=clf_mean, param_grid=param_grid, cv=3).fit(X, y)
                clf_mean = grid_search.best_estimator_
            else:
                clf_mean = DecisionTreeRegressor(max_depth=1, random_state=72).fit(X, y)
        else:
            clf_mean = DecisionTreeRegressor(max_depth=5, random_state=72)
            clf_mean.fit(X, y)

        leaf_indices = clf_mean.apply(X)

        y_leaf = pd.DataFrame({
            'Leaf': leaf_indices,
            'Y': y
        })

        clf = DecisionRules()
        clf.from_decision_tree(clf_mean)

        leaves = list(y_leaf['Leaf'].unique())
        for l in leaves:
            y = y_leaf[y_leaf['Leaf']==l]['Y']
            y = remove_outliers(y)
            min_value = np.min(y)
            max_value = np.max(y)
            dist, params = return_best_distribution(y, dist_search=DIST_SEARCH)
            sampled = sampling_from_dist(dist, params, min_value, max_value, clf.rules[l]["value"], n_sample=max(len(y), 1000))
            clf.rules[l]['dist'] = dist, params, min_value, max_value
            clf.rules[l]['sampled'] = list(sampled)
        
        models_res[res] = clf

    return models_res



# BUILD TRAINING DATASETS

def build_training_df_arrival(
        log: EventLog, 
        calendar_arrival: dict
    ) -> pd.DataFrame:

    df_log = pm4py.convert_to_dataframe(log)
    first_ts = df_log.groupby('case:concept:name')["start:timestamp"].min()
    ordered_first_ts_list = first_ts.sort_values().tolist()

    dict_df = {'hour': []} | {'weekday': []} | {'arrival_time': []}

    for i in range(1, len(ordered_first_ts_list)):
        dict_df['hour'].append(ordered_first_ts_list[i-1].hour)
        dict_df['weekday'].append(ordered_first_ts_list[i-1].weekday())
        dict_df['arrival_time'].append(max((ordered_first_ts_list[i] - ordered_first_ts_list[i-1]).total_seconds()/60 - count_false_hours(calendar_arrival, ordered_first_ts_list[i-1], ordered_first_ts_list[i])*60, 0))

    df = pd.DataFrame(dict_df)

    return df



def build_training_df_ex(
        df_features: pd.DataFrame,
        resources: list, 
        activity_labels: list, 
        calendars: dict,
        label_data_attributes: list, 
        label_data_attributes_categorical: list, 
        values_categorical: dict
    ) -> pd.DataFrame:
    
    df_et = df_features[["transition_label", "resource", "start_t", "end_t"] + label_data_attributes + activity_labels]
    df_et = df_et[~df_et["start_t"].isna()]
    df_et["execution_time"] = df_et.apply(lambda x: max((x["end_t"] - x["start_t"]).total_seconds()/60 - count_false_hours(calendars[x["resource"]], x["start_t"], x["end_t"])*60, 0), axis=1)
    df_et.drop(columns=["start_t", "end_t"], inplace=True)
    df_et.rename(columns={"transition_label": "activity_executed"}, inplace=True)
    df_et.reset_index(drop=True, inplace=True)

    for r in resources:
        df_et['resource = '+r] = (df_et['resource'] == r).astype(int)
    del df_et['resource']

    for a in label_data_attributes_categorical:
        for v in values_categorical[a]:
            df_et[a+' = '+str(v)] = (df_et[a] == v).astype(int)
        del df_et[a]

    return df_et



def build_training_df_wt(
        df_features: pd.DataFrame,
        net_transition_labels: list,
        calendars: dict, 
        label_data_attributes: list,
        label_data_attributes_categorical: list,
        values_categorical: dict
    ) -> dict:

    df_wt = df_features[["resource", "start_t", "enabled_t", "res_workload"] + label_data_attributes + net_transition_labels]
    df_wt = df_wt[~df_wt["start_t"].isna()]
    df_wt["waiting_time"] = df_wt.apply(lambda x: max((x["start_t"] - x["enabled_t"]).total_seconds()/60 - count_false_hours(calendars[x["resource"]], x["enabled_t"], x["start_t"])*60, 0), axis=1)
    df_wt.drop(columns=["start_t", "enabled_t"], inplace=True)
    df_wt.rename(columns={"res_workload": "workload"}, inplace=True)
    df_wt.reset_index(drop=True, inplace=True)

    for a in label_data_attributes_categorical:
        for v in values_categorical[a]:
            df_wt[a+' = '+str(v)] = (df_wt[a] == v).astype(int)
        del df_wt[a]

    return df_wt



# NO RULES MODE

def find_best_distribution_arrival(log: EventLog, 
        calendar_arrival: dict
    ) -> tuple:

    df_log = pm4py.convert_to_dataframe(log)
    first_ts = df_log.groupby('case:concept:name')["start:timestamp"].min()
    ordered_first_ts_list = first_ts.sort_values().tolist()

    arrival_times = []
    for i in range(1, len(ordered_first_ts_list)):
        arrival_times.append(max((ordered_first_ts_list[i] - ordered_first_ts_list[i-1]).total_seconds()/60 - count_false_hours(calendar_arrival, ordered_first_ts_list[i-1], ordered_first_ts_list[i])*60, 0))
    arrival_times = remove_outliers(arrival_times)

    dist, params = return_best_distribution(arrival_times, dist_search=DIST_SEARCH)
    min_value = np.min(arrival_times)
    max_value = np.max(arrival_times)

    return dist, params, min_value, max_value, np.mean(arrival_times)


def find_best_distribution_ex(df_features: pd.DataFrame, 
        activity_labels: list,
        calendars: dict
    ) -> dict:

    df_et = df_features[["transition_label", "resource", "start_t", "end_t"]]
    df_et = df_et[~df_et["start_t"].isna()]
    df_et["execution_time"] = df_et.apply(lambda x: max((x["end_t"] - x["start_t"]).total_seconds()/60 - count_false_hours(calendars[x["resource"]], x["start_t"], x["end_t"])*60, 0), axis=1)

    activity_exec_time_distributions = dict()

    for act in activity_labels:
        df_act = df_et[df_et['transition_label'] == act]

        exec_times = df_act['execution_time'].dropna().tolist()
        exec_times = remove_outliers(exec_times)

        dist, params = return_best_distribution(exec_times, dist_search=DIST_SEARCH)
        if len(exec_times) == 0:
            dist = 'fixed'
            params = (0,)
            max_value = 0
            min_value = 0
            mean_value = 0
        else:
            dist, params = return_best_distribution(exec_times, dist_search=DIST_SEARCH)
            min_value = np.min(exec_times)
            max_value = np.max(exec_times)
            mean_value = np.mean(exec_times)

        activity_exec_time_distributions[act] = (dist, params, min_value, max_value, mean_value)

    return activity_exec_time_distributions


def find_best_distribution_wt(df_features: pd.DataFrame,
        resources: list,
        calendars: dict
    ) -> dict:

    df_wt = df_features[["resource", "start_t", "enabled_t"]]
    df_wt = df_wt[~df_wt["start_t"].isna()]
    df_wt["waiting_time"] = df_wt.apply(lambda x: max((x["start_t"] - x["enabled_t"]).total_seconds()/60 - count_false_hours(calendars[x["resource"]], x["enabled_t"], x["start_t"])*60, 0), axis=1)
    df_wt.reset_index(drop=True, inplace=True)

    res_waiting_time_distributions = dict()

    for res in resources:
        df_res = df_wt[df_wt['resource'] == res]
        waiting_times = df_res['waiting_time'].dropna().tolist()
        waiting_times = remove_outliers(waiting_times)

        if len(waiting_times) == 0:
            dist = 'fixed'
            params = (0,)
            min_value = 0
            max_value = 0
            mean_value = 0
        else:
            dist, params = return_best_distribution(waiting_times, dist_search=DIST_SEARCH)
            min_value = np.min(waiting_times)
            max_value = np.max(waiting_times)
            mean_value = np.mean(waiting_times)

        res_waiting_time_distributions[res] = (dist, params, min_value, max_value, mean_value)

    return res_waiting_time_distributions