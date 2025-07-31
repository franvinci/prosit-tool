import pm4py
import pandas as pd
from pm4py.objects.log.obj import EventLog

from tqdm import tqdm

from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import GridSearchCV

from prosit.utils.rule_utils import DecisionRules


def discover_resources_list(log: EventLog, thr: float = 1.0) -> list:

    resource_counts = pd.Series(
        pm4py.get_event_attribute_values(log, 'org:resource'))
    resource_counts = resource_counts / resource_counts.sum()
    resource_counts = resource_counts.sort_values(ascending=False)
    resource_counts_cumsum = resource_counts.cumsum()
    resource_counts = resource_counts[resource_counts_cumsum <= thr]
    resources = resource_counts.index.tolist()

    return resources


def discover_resources_per_act(log: EventLog,
                               activities: list,
                               resources: list,
                               thr: float = 1.0) -> dict:

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


def return_multitasking_resources(df_features: pd.DataFrame, thr=0.05) -> list:

    def condition(group):
        total = len(group)
        positive = (group['res_workload'] > 0).sum()
        return (positive / total) >= thr

    filtered = df_features.groupby('resource').filter(condition)

    return filtered['resource'].unique().tolist()


def discover_weight_resources(
    df_features: pd.DataFrame,
    net_transition_labels: list,
    resources: list,
    max_depths_cv: list = range(1, 6),
    label_data_attributes: list = [],
    label_data_attributes_categorical: list = [],
    values_categorical: dict = dict()
) -> dict:

    df_features = df_features[~df_features["resource"].isna()]

    if not max_depths_cv:
        weights_r = {
            r: (df_features["resource"] == r).sum() /
            df_features["prev_enabled_resources"].apply(
                lambda r_set: r in r_set).sum()
            for r in resources
        }
    else:
        weights_r = build_models(df_features, net_transition_labels, resources,
                                 max_depths_cv, label_data_attributes,
                                 label_data_attributes_categorical,
                                 values_categorical)

    return weights_r


def build_models(
    df_features: pd.DataFrame,
    net_transition_labels: list,
    resources: list,
    max_depths_cv: list = range(1, 6),
    label_data_attributes: list = [],
    label_data_attributes_categorical: list = [],
    values_categorical: dict = dict()
) -> dict:

    param_grid = {'max_depth': max_depths_cv}

    datasets_r = build_training_datasets(df_features, net_transition_labels,
                                         resources, label_data_attributes)

    models_r = dict()

    for r in tqdm(datasets_r.keys()):
        data_r = datasets_r[r]
        if len(data_r['class'].unique()) < 2:
            models_r[r] = None
            continue

        for a in label_data_attributes_categorical:
            for v in values_categorical[a]:
                data_r[a + ' = ' + str(v)] = (data_r[a] == v).astype(int)
            del data_r[a]

        X = data_r.drop(columns=['class'])
        y = data_r['class']

        if max_depths_cv:
            clf_r_dtc = DecisionTreeClassifier(random_state=72)
            try:
                grid_search = GridSearchCV(estimator=clf_r_dtc,
                                           param_grid=param_grid,
                                           cv=3).fit(X, y)
                clf_r_dtc = grid_search.best_estimator_
            except:
                clf_r_dtc = DecisionTreeClassifier(max_depth=2,
                                                   random_state=72)
                clf_r_dtc.fit(X, y)
        else:
            clf_t_dtc = DecisionTreeClassifier(random_state=72, max_depth=1)
            clf_t_dtc.fit(X, y)

        clf_r = DecisionRules()
        clf_r.from_decision_tree(clf_r_dtc)

        if clf_r is None:
            clf_r = float(y.mode().iloc[0])

        models_r[r] = clf_r

    return models_r


def build_training_datasets(df_features: pd.DataFrame,
                            net_transition_labels: list, resources: list,
                            label_data_attributes: list) -> dict:

    df_res = df_features[["resource", "prev_enabled_resources"] + resources +
                         label_data_attributes + net_transition_labels]

    df_res = df_res.explode('prev_enabled_resources')
    df_res['class'] = (
        df_res['prev_enabled_resources'] == df_res['resource']).astype(int)

    df_res = df_res.drop(columns=['resource'])
    df_res = df_res.rename(columns={'prev_enabled_resources': 'resource'})

    datasets_r = {
        r:
        df_res[df_res["resource"] == r].drop(columns=['resource']).reset_index(
            drop=True)
        for r in resources
    }

    return datasets_r
