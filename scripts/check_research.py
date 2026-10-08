"""Small mathematical checks plus consistency of research exports."""
import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score
from run_research import ROOT, align, economic_knn
from compare_models import check_network_indices

reference = np.array([1,1,2,2,3,3])
permuted = np.array([8,8,5,5,9,9])
assert np.array_equal(align(reference,permuted),reference)
assert adjusted_rand_score(reference,permuted) == 1
points = np.array([[0.,0.],[0.,0.],[1.,0.],[10.,0.]])
graph = economic_knn(points,1,1)
assert (graph != graph.T).nnz == 0
assert np.all(graph.diagonal() == 0)
assert graph[0,1] == 1 and graph[0,3] == 0 and graph[2,3] > 0
check_network_indices()

data = json.loads((ROOT/'site/research-data.json').read_text())
for name,digest in data['inputs'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, f'Stale research input: {name}; run make research'
robust = pd.read_csv(ROOT/'artifacts/research/subsamples.csv')
assert len(robust) == 24*data['protocol']['subsamples']
assert robust.groupby('trial').date.nunique().eq(24).all()
assert robust.ari.between(-1,1).all() and robust.agreement.between(0,1).all()
assert np.isclose(robust.groupby('trial').ari.mean().median(),data['robustness']['median'])
networks = pd.read_csv(ROOT/'artifacts/research/networks.csv')
assert len(networks) == 4*24
assert np.isfinite(networks.drop(columns=['model','date','temporal_ari']).to_numpy()).all()
assert np.allclose(networks.mq,3*networks.avi)
assert np.allclose(networks.avu,2/3)
folds = pd.read_csv(ROOT/'artifacts/research/external_folds.csv')
assert len(folds) == 3*2*data['protocol']['folds']
for row in data['external']:
    group = folds[(folds.metric==row['metric']) & (folds.year==row['year'])]
    baseline = np.average(group.baseline_mse,weights=group.n)
    extended = np.average(group.type_mse,weights=group.n)
    assert group.n.sum() == row['n'] == sum(p['n'] for p in row['profiles'])
    assert np.isclose(row['mse_reduction_percent'],100*(1-extended/baseline))
print('Research: label permutation, graph ties, ICVI, provenance, 480 subsamples, 96 network rows, 30 validation folds OK')
