import hashlib
import itertools
import json

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.neighbors import NearestNeighbors

from run_sensitivity import ROOT, smooth, graph_from_neighbors, transport_representation, agreement

# An isolate must retain its features, even at 100% neighbor weight.
x = np.array([[1.,2.],[4.,5.],[7.,8.]])
g = sparse.csr_matrix([[0.,1.,0.],[1.,0.,0.],[0.,0.,0.]])
assert np.array_equal(smooth(x,g,1),x[[1,0,2]])
# Removing access must not cause the last remaining expense feature to disappear from edge weights.
blocks = np.tile(x,(24,1))
first = transport_representation(blocks,['relative_spend','marketplace_share'],g,3,.2,1)
reordered = transport_representation(blocks[:,::-1],['marketplace_share','relative_spend'],g,3,.2,1)
assert np.allclose(first,reordered[:,::-1])
# Matching cluster names is independent of their integer encoding.
ref = np.tile([1,2,3],24)
rows, profiles = agreement(ref,np.tile([8,4,9],24),3)
assert all(r['ari']==1 and r['agreement']==1 for r in rows)
assert all(p['jaccard']==1 for p in profiles)
for distance in ['euclidean','cosine']:
    points = np.array([[1.,0.],[1.,0.],[0.,1.],[-1.,0.]])
    ds,js = NearestNeighbors(n_neighbors=3,metric=distance).fit(points).kneighbors(points)
    graph = graph_from_neighbors(ds,js,1,1)
    assert (graph != graph.T).nnz == 0 and np.all(graph.diagonal()==0)
    assert graph[0,1]==1 and np.isfinite(graph.data).all()

data = json.loads((ROOT/'site/sensitivity-data.json').read_text())
for name,digest in data['inputs'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, f'Stale {name}; run make sensitivity'
assert len(data['ablations'])==8
months = pd.read_csv(ROOT/'artifacts/research/feature_ablation_monthly.csv')
assert len(months)==8*24
for row in data['ablations']:
    values = months[months.removed==','.join(row['dropped'])]
    assert len(values)==24 and np.isclose(values.ari.mean(),row['ari'])
    assert len(row['profiles'])==3 and all(0<=p['jaccard']<=1 for p in row['profiles'])
    assert sum(p['count_december'] for p in row['profiles'])==2016
p = data['protocol']
expected = set(itertools.product(p['distances'],p['neighbors'],p['bandwidths']))
assert {(r['distance'],r['neighbors'],r['bandwidth']) for r in data['networks']}==expected
monthly = pd.read_csv(ROOT/'artifacts/research/network_grid_monthly.csv')
assert len(monthly)==24*len(expected)
for row in data['networks']:
    group=monthly[(monthly.distance==row['distance']) & (monthly.neighbors==row['neighbors']) & (monthly.bandwidth==row['bandwidth'])]
    assert len(group)==24 and group.temporal_ari.notna().sum()==23
    for key in ['silhouette','ch','s_dbw','avi','avu','mq','reference_ari','temporal_ari','mean_degree']:
        assert np.isfinite(row[key]) and np.isclose(group[key].mean(),row[key])
    assert np.isclose(row['mq'],3*row['avi']) and np.isclose(row['avu'],2/3)
print(f'Sensitivity: isolates, feature order, label matching, tied neighbors, 192 ablation rows and {len(monthly)} network rows OK')
