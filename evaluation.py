import pandas as pd
import pm4py
import numpy as np

from scipy.stats import entropy
from scipy.stats import wasserstein_distance

from log_distance_measures.config import EventLogIDs

from log_distance_measures.absolute_event_distribution import absolute_event_distribution_distance, discretize_to_hour
from log_distance_measures.case_arrival_distribution import case_arrival_distribution_distance
from log_distance_measures.circadian_event_distribution import circadian_event_distribution_distance
from log_distance_measures.circadian_workforce_distribution import circadian_workforce_distribution_distance
from log_distance_measures.config import AbsoluteTimestampType
from log_distance_measures.control_flow_log_distance import control_flow_log_distance
from log_distance_measures.cycle_time_distribution import cycle_time_distribution_distance
from log_distance_measures.n_gram_distribution import n_gram_distribution_distance
from log_distance_measures.relative_event_distribution import relative_event_distribution_distance

import datetime



def evaluate(original_log, simulated_log, metrics_labels=["cfld", "ngd", "red", "aed", "red", "aed", "car", "ctd", "car_entropy", "hwd", "ctd_entropy", "etd_entropy"]):

    event_log_ids = EventLogIDs(
        case="case:concept:name",
        activity="concept:name",
        resource="org:resource",
        start_time="start:timestamp",
        end_time="time:timestamp"
    )

    original_log = original_log.copy()
    simulated_log = simulated_log.copy()

    original_log[event_log_ids.start_time] = pd.to_datetime(original_log[event_log_ids.start_time], format='ISO8601', utc=True)
    original_log[event_log_ids.end_time] = pd.to_datetime(original_log[event_log_ids.end_time], format='ISO8601', utc=True)

    simulated_log[event_log_ids.start_time] = pd.to_datetime(simulated_log[event_log_ids.start_time], format='ISO8601', utc=True)
    simulated_log[event_log_ids.end_time] = pd.to_datetime(simulated_log[event_log_ids.end_time], format='ISO8601', utc=True)

    metrics = dict()

    if "cfld" in metrics_labels:
        metrics['cfld'] = control_flow_log_distance(
            original_log, 
            event_log_ids, 
            simulated_log, 
            event_log_ids
        )

    if ("3gd" in metrics_labels) or ("ngd" in metrics_labels):
        metrics['3gd'] = n_gram_distribution_distance(
            original_log, 
            event_log_ids, 
            simulated_log, 
            event_log_ids, 
            n=3,
        )
    
    if "2gd" in metrics_labels:
        metrics['2gd'] = n_gram_distribution_distance(
            original_log, 
            event_log_ids, 
            simulated_log, 
            event_log_ids, 
            n=2,
        )

    if "aed" in metrics_labels:
        metrics['aed'] = absolute_event_distribution_distance(
                original_log,
                event_log_ids,
                simulated_log,
                event_log_ids,
                AbsoluteTimestampType.BOTH,
                discretize_to_hour,
        )

    if "red" in metrics_labels:
        metrics['red'] = relative_event_distribution_distance(
            original_log,
            event_log_ids,
            simulated_log,
            event_log_ids,
            AbsoluteTimestampType.BOTH,
        )

    if "ced" in metrics_labels:
        metrics['ced'] = circadian_event_distribution_distance(
            original_log,
            event_log_ids,
            simulated_log,
            event_log_ids,
            AbsoluteTimestampType.BOTH,
        )

    if "cwd" in metrics_labels:
        metrics['cwd'] = circadian_workforce_distribution_distance(
            original_log,
            event_log_ids,
            simulated_log,
            event_log_ids
        )

    if "car" in metrics_labels:
        metrics['car'] = case_arrival_distribution_distance(
            original_log,
            event_log_ids,
            simulated_log,
            event_log_ids,
        )

    if "ctd" in metrics_labels:
        metrics['ctd'] = cycle_time_distribution_distance(
                original_log,
                event_log_ids,
                simulated_log,
                event_log_ids,
                datetime.timedelta(hours=1),
        )

    if "hwd" in metrics_labels:
        metrics["hwd"] = compute_handover_error(simulated_log, original_log)

    if "rfld" in metrics_labels:
        metrics["rfld"] = compute_resource_flow_distance(simulated_log, original_log)

    if "r2gd" in metrics_labels:
        metrics["r2gd"] = compute_resource_ngd(simulated_log, original_log, n=2)
    if "r3gd" in metrics_labels:
        metrics["r3gd"] = compute_resource_ngd(simulated_log, original_log, n=3)
    if "r4gd" in metrics_labels:
        metrics["r4gd"] = compute_resource_ngd(simulated_log, original_log, n=4)
    if "r5gd" in metrics_labels:
        metrics["r5gd"] = compute_resource_ngd(simulated_log, original_log, n=5)

    if "car_entropy" in metrics_labels:
        metrics['car_entropy'] = compute_atd_entropy(simulated_log)

    if "ctd_entropy" in metrics_labels:
        metrics['ctd_entropy'] = compute_ctd_entropy(simulated_log)

    if "etd_entropy" in metrics_labels:
        metrics['etd_entropy'] = compute_etd_entropy(simulated_log)

    return metrics


def compute_atd_entropy(df_log: pd.DataFrame) -> float:

    first_ts = df_log.groupby('case:concept:name')["start:timestamp"].min()
    ordered_first_ts_list = first_ts.sort_values().tolist()

    arrival_times = []
    for i in range(1, len(ordered_first_ts_list)):
        arrival_times.append((ordered_first_ts_list[i] - ordered_first_ts_list[i-1]).total_seconds()/60)

    if len(arrival_times) < 2:
        return 0.0

    hist, _ = np.histogram(arrival_times, bins='auto', density=True)
    hist = hist[hist > 0]
    if hist.size == 0 or np.sum(hist) == 0:
        return 0.0
    probs = hist / np.sum(hist)
    atd_entr = entropy(probs)

    return float(atd_entr)


def compute_ctd_entropy(df_log: pd.DataFrame) -> float:

    log = pm4py.convert_to_event_log(df_log)
    cycle_times = []
    for trace in log:
        if not trace:
            continue
        start = trace[0]['start:timestamp']
        end = trace[-1]['time:timestamp']
        cycle_times.append((end-start).total_seconds()//60)

    if len(cycle_times) < 2:
        return 0.0

    hist, _ = np.histogram(cycle_times, bins='auto', density=True)
    if np.sum(hist) == 0:
        return 0.0
    probs = hist / np.sum(hist)
    ctd_entr = entropy(probs)

    return float(ctd_entr)


def compute_etd_entropy(df_log: pd.DataFrame) -> float:

    activities = list(df_log["concept:name"].unique())
    etd_entropies = []
    for act in activities:
        df_log_act = df_log[df_log["concept:name"] == act]
        if df_log_act.empty:
            continue
        ex_times = (df_log_act["time:timestamp"] - df_log_act["start:timestamp"]).apply(lambda x: x.total_seconds() // 60)
        if len(ex_times) < 2:
            continue
        hist, _ = np.histogram(list(ex_times), bins='auto', density=True)
        if np.sum(hist) == 0:
            continue
        probs = hist / np.sum(hist)
        etd_entropies.append(entropy(probs))

    return float(np.mean(etd_entropies)) if etd_entropies else 0.0


def build_handover_matrix(df: pd.DataFrame, resources: list, case_id_col: str='case:concept:name', resource_col: str='org:resource') -> pd.DataFrame:

    res_idx = {res: i for i, res in enumerate(resources)}
    matrix = np.zeros((len(resources), len(resources)), dtype=int)

    for case_id, group in df.groupby(case_id_col):
        resource_sequence = group[resource_col].tolist()
        for i in range(len(resource_sequence) - 1):
            from_res = resource_sequence[i]
            to_res = resource_sequence[i + 1]
            if from_res in res_idx and to_res in res_idx:
                matrix[res_idx[from_res], res_idx[to_res]] += 1

    handover_matrix = pd.DataFrame(matrix, index=resources, columns=resources)

    return handover_matrix


def compute_handover_error(df_sim: pd.DataFrame, df_test: pd.DataFrame, case_id_col: str='case:concept:name', resource_col: str='org:resource') -> int:
    
    resources = list(set(df_sim[resource_col]) | set(df_test[resource_col]))

    handover_matrix_sim = build_handover_matrix(df_sim, resources, case_id_col=case_id_col, resource_col=resource_col)
    handover_matrix_test = build_handover_matrix(df_test, resources, case_id_col=case_id_col, resource_col=resource_col)

    return float((handover_matrix_sim - handover_matrix_test).abs().sum().sum())


def compute_resource_flow_distance(df_sim: pd.DataFrame, df_test: pd.DataFrame):

    event_log_ids = EventLogIDs(
        case="case:concept:name",
        activity="org:resource",
        start_time="start:timestamp",
        end_time="time:timestamp"
    )

    df_test = df_test.copy()
    df_sim = df_sim.copy()

    df_test[event_log_ids.start_time] = pd.to_datetime(df_test[event_log_ids.start_time], format='ISO8601', utc=True)
    df_test[event_log_ids.end_time] = pd.to_datetime(df_test[event_log_ids.end_time], format='ISO8601', utc=True)

    df_sim[event_log_ids.start_time] = pd.to_datetime(df_sim[event_log_ids.start_time], format='ISO8601', utc=True)
    df_sim[event_log_ids.end_time] = pd.to_datetime(df_sim[event_log_ids.end_time], format='ISO8601', utc=True)

    rfld = control_flow_log_distance(
        df_test, 
        event_log_ids, 
        df_sim, 
        event_log_ids
    )

    return rfld


def compute_log_kpis(df_log: pd.DataFrame) -> dict:
    """Return human-readable KPIs for an event log (seconds for time-based ones).

    Designed to populate a real-vs-simulated comparison table; pair the dict
    returned for the original log with the one returned for the simulated log.
    """
    if df_log is None or len(df_log) == 0:
        return {
            'num_cases': 0,
            'num_events': 0,
            'num_activities': 0,
            'num_resources': 0,
            'cycle_time_mean_sec': 0.0,
            'cycle_time_median_sec': 0.0,
            'throughput_cases_per_day': 0.0,
        }

    df = df_log.copy()
    df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], format='ISO8601', utc=True)
    df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], format='ISO8601', utc=True)

    case_col = 'case:concept:name'
    activity_col = 'concept:name'
    resource_col = 'org:resource' if 'org:resource' in df.columns else None

    grouped = df.groupby(case_col)
    case_starts = grouped['start:timestamp'].min()
    case_ends = grouped['time:timestamp'].max()
    cycle_times_sec = (case_ends - case_starts).dt.total_seconds()

    num_cases = int(case_starts.shape[0])
    num_events = int(len(df))
    num_activities = int(df[activity_col].nunique())
    num_resources = int(df[resource_col].dropna().nunique()) if resource_col else 0

    span_seconds = (df['time:timestamp'].max() - df['start:timestamp'].min()).total_seconds()
    throughput_cases_per_day = float(num_cases / (span_seconds / 86400.0)) if span_seconds > 0 else 0.0

    return {
        'num_cases': num_cases,
        'num_events': num_events,
        'num_activities': num_activities,
        'num_resources': num_resources,
        'cycle_time_mean_sec': float(cycle_times_sec.mean()) if len(cycle_times_sec) else 0.0,
        'cycle_time_median_sec': float(cycle_times_sec.median()) if len(cycle_times_sec) else 0.0,
        'throughput_cases_per_day': throughput_cases_per_day,
    }


def compute_log_charts(df_real: pd.DataFrame, df_sim: pd.DataFrame) -> dict:
    """Return chart-ready arrays for the KPI comparison view.

    Builds three datasets: cycle-time histogram, arrivals per day, and per-
    resource event counts. Real and simulated share bin edges / time axes so
    the frontend can overlay them.
    """
    def _prep(df):
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], format='ISO8601', utc=True)
        df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], format='ISO8601', utc=True)
        return df

    df_real = _prep(df_real)
    df_sim = _prep(df_sim)

    # --- cycle time histogram (seconds) -----------------------------------
    def _cycle_times_sec(df):
        if df is None:
            return np.array([])
        case_starts = df.groupby('case:concept:name')['start:timestamp'].min()
        case_ends = df.groupby('case:concept:name')['time:timestamp'].max()
        return (case_ends - case_starts).dt.total_seconds().values

    ct_real = _cycle_times_sec(df_real)
    ct_sim = _cycle_times_sec(df_sim)
    combined = np.concatenate([ct_real, ct_sim]) if len(ct_real) + len(ct_sim) else np.array([0.0, 1.0])
    n_bins = 20
    if combined.max() > combined.min():
        edges = np.linspace(combined.min(), combined.max(), n_bins + 1)
    else:
        edges = np.linspace(0.0, max(1.0, combined.max() + 1.0), n_bins + 1)
    real_hist, _ = np.histogram(ct_real, bins=edges) if len(ct_real) else (np.zeros(n_bins, dtype=int), edges)
    sim_hist, _ = np.histogram(ct_sim, bins=edges) if len(ct_sim) else (np.zeros(n_bins, dtype=int), edges)
    bin_centers_sec = ((edges[:-1] + edges[1:]) / 2.0).tolist()

    # --- arrivals per day -------------------------------------------------
    def _arrivals_per_day(df):
        if df is None:
            return pd.Series(dtype=int)
        firsts = df.groupby('case:concept:name')['start:timestamp'].min().dt.floor('D')
        return firsts.value_counts().sort_index()

    real_arr = _arrivals_per_day(df_real)
    sim_arr = _arrivals_per_day(df_sim)
    all_days = sorted(set(real_arr.index).union(sim_arr.index))
    arrivals_labels = [d.isoformat() for d in all_days]
    arrivals_real = [int(real_arr.get(d, 0)) for d in all_days]
    arrivals_sim = [int(sim_arr.get(d, 0)) for d in all_days]

    # --- resource utilization (top-N union) -------------------------------
    def _res_counts(df):
        if df is None or 'org:resource' not in df.columns:
            return pd.Series(dtype=int)
        return df['org:resource'].dropna().value_counts()

    real_rc = _res_counts(df_real)
    sim_rc = _res_counts(df_sim)
    union_top = (real_rc.add(sim_rc, fill_value=0)).sort_values(ascending=False).head(15)
    resource_labels = [str(x) for x in union_top.index.tolist()]
    resource_real = [int(real_rc.get(name, 0)) for name in resource_labels]
    resource_sim = [int(sim_rc.get(name, 0)) for name in resource_labels]

    return {
        'cycle_time': {
            'bin_centers_sec': bin_centers_sec,
            'real_counts': real_hist.tolist(),
            'simulated_counts': sim_hist.tolist(),
        },
        'arrivals_per_day': {
            'days': arrivals_labels,
            'real': arrivals_real,
            'simulated': arrivals_sim,
        },
        'resource_counts': {
            'resources': resource_labels,
            'real': resource_real,
            'simulated': resource_sim,
        },
    }


def compute_resource_ngd(df_sim: pd.DataFrame, df_test: pd.DataFrame, n=3):

    event_log_ids = EventLogIDs(
        case="case:concept:name",
        activity="org:resource",
        start_time="start:timestamp",
        end_time="time:timestamp"
    )

    df_test = df_test.copy()
    df_sim = df_sim.copy()

    df_test[event_log_ids.start_time] = pd.to_datetime(df_test[event_log_ids.start_time], format='ISO8601', utc=True)
    df_test[event_log_ids.end_time] = pd.to_datetime(df_test[event_log_ids.end_time], format='ISO8601', utc=True)

    df_sim[event_log_ids.start_time] = pd.to_datetime(df_sim[event_log_ids.start_time], format='ISO8601', utc=True)
    df_sim[event_log_ids.end_time] = pd.to_datetime(df_sim[event_log_ids.end_time], format='ISO8601', utc=True)

    ngd = n_gram_distribution_distance(
            df_test, 
            event_log_ids, 
            df_sim, 
            event_log_ids, 
            n=n,
        )

    return ngd