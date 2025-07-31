import pandas as pd
from prosit.discovery.resource_discovery import build_training_datasets
from tqdm import tqdm
from river import tree
from prosit.utils.rule_utils import DecisionRules


def incremental_resource_weights_learning(
        df_features: pd.DataFrame,
        net_transition_labels: list,
        resources: list,
        max_depth: int = 3,
        grace_period: int = 1000,
        label_data_attributes: list = [],
        label_data_attributes_categorical: list = [],
        values_categorical: dict = dict(),
):

    df_features = df_features[~df_features["resource"].isna()]

    datasets_r = build_training_datasets(df_features, net_transition_labels,
                                         resources, label_data_attributes)

    models_r = dict()

    for t in tqdm(datasets_r.keys()):
        data_r = datasets_r[t]
        if len(data_r['class'].unique()) < 2:
            models_r[t] = None
            continue

        for a in label_data_attributes_categorical:
            for v in values_categorical[a]:
                data_r[a + ' = ' + str(v)] = (data_r[a] == v).astype(int)
            del data_r[a]

        m_t = tree.HoeffdingAdaptiveTreeClassifier(seed=72,
                                                   max_depth=max_depth,
                                                   grace_period=grace_period,
                                                   leaf_prediction="mc")

        for _, row in data_r.iterrows():
            X_row = row.drop('class').to_dict()
            y_row = row['class']
            m_t.learn_one(X_row, y_row)

        clf_t = DecisionRules()
        clf_t.from_river_decision_tree(m_t)
        models_r[t] = clf_t

    return models_r
