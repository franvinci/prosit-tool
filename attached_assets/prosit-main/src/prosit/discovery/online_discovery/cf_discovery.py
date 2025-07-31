import pandas as pd
from prosit.discovery.cf_discovery import build_training_datasets
from tqdm import tqdm
from river import tree
from prosit.utils.rule_utils import DecisionRules


def incremental_transition_weights_learning(
        df_features: pd.DataFrame,
        net_transition_labels: list, 
        max_depth: int = 3,
        grace_period: int = 1000,
        label_data_attributes: list = [], 
        label_data_attributes_categorical: list = [], 
        values_categorical: dict = dict(),
    ):

    datasets_t = build_training_datasets(
                                            df_features,
                                            net_transition_labels,
                                            label_data_attributes
                                        )

    models_t = dict()

    for t in tqdm(datasets_t.keys()):
        data_t = datasets_t[t]
        if len(data_t['class'].unique())<2:
            models_t[t] = None
            continue
        
        for a in label_data_attributes_categorical:
            for v in values_categorical[a]:
                data_t[a+' = '+str(v)] = (data_t[a] == v).astype(int)
            del data_t[a]

        m_t = tree.HoeffdingAdaptiveTreeClassifier(seed=72, max_depth=max_depth, grace_period=grace_period, leaf_prediction="mc")

        for _, row in data_t.iterrows():
            X_row = row.drop('class').to_dict()
            y_row = row['class']
            m_t.learn_one(X_row, y_row)

        clf_t = DecisionRules()
        clf_t.from_river_decision_tree(m_t)
        models_t[t] = clf_t
    
    return models_t