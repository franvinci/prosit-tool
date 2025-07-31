from tqdm import tqdm
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import GridSearchCV

from prosit.utils.rule_utils import DecisionRules




def discover_weight_transitions(
        df_features: pd.DataFrame,
        net_transition_labels: list, 
        max_depths_cv: list = range(1, 6),
        label_data_attributes: list = [], 
        label_data_attributes_categorical: list = [], 
        values_categorical: dict = dict(),
        transition_model_type: str = 'DecisionTree'
    ) -> dict :

    if not max_depths_cv:
        transitions = df_features['transition'].unique()
        transition_weights = {t: (df_features["transition"] == t).sum() / df_features["prev_enabled_transitions"].apply(lambda t_set: t in t_set).sum() for t in transitions}
    else:
        transition_weights = build_models(
                                            df_features,
                                            net_transition_labels,
                                            label_data_attributes,
                                            label_data_attributes_categorical,
                                            values_categorical,
                                            model_type=transition_model_type,
                                            max_depths_cv=max_depths_cv
                                        )

    return transition_weights


def build_models(
        df_features: pd.DataFrame,
        net_transition_labels: list,
        label_data_attributes: list,
        label_data_attributes_categorical: list,
        values_categorical: dict,
        model_type: str = 'DecisionTree', 
        max_depths_cv: list = range(1,6)
    ) -> dict :
    
    datasets_t = build_training_datasets(
                    df_features,
                    net_transition_labels, 
                    label_data_attributes
                )

    param_grid = {'max_depth': max_depths_cv}

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

        X = data_t.drop(columns=['class'])
        y = data_t['class']

        if model_type == 'LogisticRegression':
            clf_t = LogisticRegression(random_state=72).fit(X, y)

        elif model_type == 'DecisionTree':

            if max_depths_cv:
                clf_t_dtc = DecisionTreeClassifier(random_state=72)
                try:
                    grid_search = GridSearchCV(estimator=clf_t_dtc, param_grid=param_grid, cv=3).fit(X, y)
                    clf_t_dtc = grid_search.best_estimator_
                except:
                    clf_t_dtc = DecisionTreeClassifier(max_depth=2, random_state=72)
                    clf_t_dtc.fit(X, y)
            else:
                clf_t_dtc = DecisionTreeClassifier(random_state=72, max_depth=1)
                clf_t_dtc.fit(X, y)

            clf_t = DecisionRules()
            clf_t.from_decision_tree(clf_t_dtc)

        if clf_t is None:
            clf_t = float(y.mode().iloc[0])

        models_t[t] = clf_t
    
    return models_t



def build_training_datasets(
        df_features: pd.DataFrame,
        net_transition_labels: list, 
        label_data_attributes: list
    ) -> dict:

    df_cf = df_features[["transition"] + ["prev_enabled_transitions"] + label_data_attributes + net_transition_labels]

    df_cf = df_cf.explode('prev_enabled_transitions')
    df_cf['class'] = (df_cf['prev_enabled_transitions'] == df_cf['transition']).astype(int)

    df_cf = df_cf.drop(columns=['transition'])
    df_cf = df_cf.rename(columns={'prev_enabled_transitions': 'transition'})
        
    net_transitions = df_cf['transition'].unique()
    datasets_t = {t: df_cf[df_cf["transition"] == t].drop(columns=['transition']).reset_index(drop=True) for t in net_transitions}

    return datasets_t
