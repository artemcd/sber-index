"""Event matching checks and consistency of the complete decision-check artifacts."""
import hashlib
import json

import numpy as np
import pandas as pd

from run_decision_checks import ROOT, FEATURES, transition_events, score_events, generate

truth = np.array([[1],[1],[1],[2],[2],[2]])
assert transition_events(truth) == [(0,3,1,2)]
assert transition_events(np.array([[1],[1],[2],[2]])) == []
perfect = score_events(truth,transition_events(truth),2)
assert perfect['precision']==perfect['recall']==1 and perfect['false_events']==0
# A duplicated prediction must never count the same true event twice.
duplicate = score_events(truth,[(0,3,1,2),(0,4,1,2)],2)
assert duplicate['matched_events']==1 and duplicate['false_events']==1
assert score_events(truth,[(0,3,2,1)],2)['matched_events']==0
assert score_events(truth,[(0,5,1,2)],2)['matched_events']==1
assert score_events(truth,[(0,6,1,2)],2)['matched_events']==0
stable = np.ones((6,2),dtype=int)
assert score_events(stable,[],2)['recall'] is None
assert score_events(stable,[],2)['precision'] is None
false = score_events(stable,[(0,3,1,2)],2)
assert false['precision']==0 and false['false_stable_percent']==50

data = json.loads((ROOT/'site/decision-data.json').read_text())
p = data['protocol']
assert data['scope']=='base_monthly'
assert set(data['runtime'])=={'python','numpy','pandas','scipy','sklearn'}
assert all(isinstance(v,str) and v for v in data['runtime'].values())
assert all(f'scripts/{name}.py' in data['inputs'] for name in ['run_decision_checks','run_baseline','run_dynamic_model','run_graph_model','run_research','interpret_clusters'])
for name,digest in data['inputs'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,f'Stale {name}; run make decisions'
centers = np.array(data['calibration']['centers'])
zeros = np.zeros((len(FEATURES),len(FEATURES)))
scenario = next(s for s in p['scenarios'] if s['id']=='calibrated')
x,g,t = generate(centers,zeros,zeros,p,scenario,0)
x2,g2,t2 = generate(centers,zeros,zeros,p,scenario,0)
assert np.array_equal(x,x2) and (g != g2).nnz==0 and np.array_equal(t,t2)
assert (g != g.T).nnz==0 and np.all(g.diagonal()==0)
assert np.sum(t[p['change_month']]!=t[p['change_month']-1])==int(p['synthetic_nodes']*p['change_fraction'])
assert np.all(t[p['change_month']:]==t[p['change_month']])
assert np.all(x.reshape(24,-1,len(FEATURES))[:,:,-1]==x.reshape(24,-1,len(FEATURES))[0,:,-1])

samples = pd.read_csv(ROOT/'artifacts/research/cluster_count_subsamples.csv')
assert len(samples)==len(p['cluster_counts'])*p['subsamples']
assert samples.groupby('run').k.apply(list).tolist()==[p['cluster_counts']]*p['subsamples']
assert sum(r['count'] for r in data['two_type_contingency'])==2016
for row in data['cluster_counts']:
    group=samples[samples.k==row['k']]
    assert np.isclose(group.mean_monthly_ari.median(),row['subsample_ari_median'])
    assert np.isclose(group.min_cluster_jaccard.median(),row['min_jaccard_median'])
    assert 0 < row['min_monthly_share'] <= 1/row['k']
runs = pd.read_csv(ROOT/'artifacts/research/synthetic_transition_runs.csv')
assert len(runs)==len(p['scenarios'])*p['synthetic_runs']*4
for row in data['synthetic']:
    group=runs[(runs.scenario==row['scenario'])&(runs.model==row['model'])&(runs.rule==row['rule'])]
    assert len(group)==p['synthetic_runs']
    for key in ['true_events','detected_events','matched_events','false_events']:
        assert group[key].sum()==row[key]
    assert row['matched_events'] <= min(row['true_events'],row['detected_events'])
    assert row['false_events']==row['detected_events']-row['matched_events']
    assert np.isclose(100*group.false_stable_nodes.sum()/group.stable_nodes.sum(),row['false_stable_percent'])
    assert row['precision'] is None or np.isclose(row['precision'],row['matched_events']/row['detected_events'])
    assert row['recall'] is None or np.isclose(row['recall'],row['matched_events']/row['true_events'])
print(f'Decisions: event direction, tolerance, one-to-one matching, empty denominators, deterministic generator, {len(samples)} subsamples and {len(runs)} synthetic runs OK')
