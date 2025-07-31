from pm4py.objects.log.obj import EventLog
from prosit.discovery.time_discovery import build_training_df_ex, build_training_df_arrival, build_training_df_wt
from tqdm import tqdm
import pandas as pd
from river import tree
from prosit.utils.rule_utils import DecisionRules


def incremental_model_arrival_learning(
                                        log: EventLog, 
                                        calendar_arrival: dict, 
                                        max_depth: int = 3,
                                        grace_period: int = 1000,
                                    ):

    df = build_training_df_arrival(log, calendar_arrival)

    clf_arrival = tree.HoeffdingAdaptiveTreeRegressor(seed=72, max_depth=max_depth, grace_period=grace_period, leaf_prediction="mean")

    for _, row in df.iterrows():
        X_row = row.drop('arrival_time').to_dict()
        y_row = row['arrival_time']
        clf_arrival.learn_one(X_row, y_row)

    model_arrival = DecisionRules()
    model_arrival.from_river_decision_tree(clf_arrival, distribution=True, min_value=df['arrival_time'].min(), max_value=df['arrival_time'].max())

    return model_arrival


def incremental_execution_time_learning(
                                            df_features: pd.DataFrame, 
                                            net_transition_labels: list,
                                            resources: list, 
                                            calendars: dict, 
                                            max_depth: int = 3,
                                            grace_period: int = 1000,
                                            label_data_attributes: list = [], 
                                            label_data_attributes_categorical: list = [], 
                                            values_categorical: dict = dict(),
                                        ) -> dict:
    
    df = build_training_df_ex(
                                df_features,
                                resources, 
                                net_transition_labels, 
                                calendars,
                                label_data_attributes, 
                                label_data_attributes_categorical, 
                                values_categorical
                            )

    models_act = dict()
    
    for act in tqdm(net_transition_labels):

        df_act = df[df['activity_executed'] == act].iloc[:,1:]
            
        clf_act = tree.HoeffdingAdaptiveTreeRegressor(seed=72, max_depth=max_depth, grace_period=grace_period, leaf_prediction="mean")

        for _, row in df_act.iterrows():
            X_row = row.drop('execution_time').to_dict()
            y_row = row['execution_time']
            clf_act.learn_one(X_row, y_row)

        clf = DecisionRules()
        clf.from_river_decision_tree(clf_act, distribution=True, min_value=df_act['execution_time'].min(), max_value=df_act['execution_time'].max())
        models_act[act] = clf

    return models_act


def incremental_waiting_time_learning(
                                        df_features: pd.DataFrame,
                                        net_transition_labels: list, 
                                        resources: list,
                                        calendars: dict, 
                                        label_data_attributes: list, 
                                        label_data_attributes_categorical: list, 
                                        values_categorical: dict, 
                                        max_depth: int = 3,
                                        grace_period: int = 1000
                                    ) -> dict:

    df = build_training_df_wt(
                                df_features,
                                net_transition_labels,
                                calendars, 
                                label_data_attributes,
                                label_data_attributes_categorical,
                                values_categorical
                            )

    models_res = dict()
    for res in tqdm(resources):
        df_res = df[df['resource'] == res].iloc[:,1:]

        clf_res = tree.HoeffdingAdaptiveTreeRegressor(seed=72, max_depth=max_depth, grace_period=grace_period, leaf_prediction="mean")

        for _, row in df_res.iterrows():
            X_row = row.drop('waiting_time').to_dict()
            y_row = row['waiting_time']
            clf_res.learn_one(X_row, y_row)

        clf = DecisionRules()
        clf.from_river_decision_tree(clf_res, distribution=True, min_value=df_res['waiting_time'].min(), max_value=df_res['waiting_time'].max())
        models_res[res] = clf

    return models_res