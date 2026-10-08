"""Feature ablations and a fixed economic-network grid for the final monthly model."""
import hashlib
import itertools
import json

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.metrics import adjusted_rand_score, silhouette_score, calinski_harabasz_score
from sklearn.neighbors import NearestNeighbors
from threadpoolctl import threadpool_limits

from run_baseline import ROOT, FEATURES
from run_dynamic_model import prepare_monthly, scaled_monthly, load_config, fit_model, economic_graph
from run_graph_model import normalized
from run_research import transport, align
from compare_models import s_dbw, network_indices

OUT = ROOT / 'artifacts/research'
NAMES = dict(zip(FEATURES, ['Уровень расходов', 'Здоровье', 'Маркетплейсы', 'Общепит', 'Продукты', 'Транспорт', 'Доступность рынков']))


def smooth(block, graph, mix):
    neighbors = normalized(graph) @ block
    isolated = np.asarray(graph.sum(axis=1)).ravel() == 0
    neighbors[isolated] = block[isolated]
    return (1-mix)*block + mix*neighbors


def transport_representation(x, features, graph, n, mix, bandwidth):
    economic_columns = [i for i, name in enumerate(features) if name != 'log_market_access']
    return np.vstack([smooth(block, economic_graph(graph, block[:, economic_columns], bandwidth), mix)
                      for block in x.reshape(24, n, -1)])


def agreement(reference, candidate, n):
    aligned = align(reference, candidate)
    rows = []
    for month, (a,b) in enumerate(zip(reference.reshape(24,n), aligned.reshape(24,n))):
        rows.append({'month':month+1, 'ari':adjusted_rand_score(a,b), 'agreement':np.mean(a==b)})
    profiles = [{'cluster':int(c), 'jaccard':float(np.sum((reference==c)&(aligned==c))/np.sum((reference==c)|(aligned==c))),
                 'reference_count_december':int(np.sum(reference[-n:]==c)), 'count_december':int(np.sum(aligned[-n:]==c))}
                for c in np.unique(reference)]
    return rows, profiles


def graph_from_neighbors(distances, indices, k, bandwidth):
    rows, cols, values = [], [], []
    for i, (ds, js) in enumerate(zip(distances, indices)):
        keep = js != i
        chosen, ds = js[keep][:k], ds[keep][:k]
        rows.extend([i]*len(chosen)); cols.extend(chosen)
        values.extend(np.exp(-np.maximum(ds,0)**2/(2*bandwidth**2)))
    graph = sparse.csr_matrix((values,(rows,cols)),shape=(len(indices),len(indices)))
    graph = graph.maximum(graph.T)
    graph.eliminate_zeros()
    return graph


def write_report(data):
    lines = ['# От каких признаков и связей зависит типология', '',
        'Проверяется основная помесячная модель: 2016 территорий, 24 месяца, K = 3. Готовые назначения не заменяются результатами перебора. `make sensitivity` повторяет эти проверки; `make research` и `make all` включают их. Настройки: `config/sensitivity.json` и `config/dynamic_model.json`.', '',
        '## Удаление признаков', '',
        'По очереди удаляем каждый из семи признаков, затем совместно маркетплейсы и доступность рынков. Во всех опытах заново обучаем KMeans с теми же K, seed, n_init и долей окружения. Стандартизация оставшихся признаков совпадает с основной моделью: её поколоночное вычисление не зависит от удаляемого столбца. Транспортная топология фиксирована. Экономические веса транспортных рёбер пересчитываются без удалённого признака. Доступность рынков изначально не входила в веса рёбер, поэтому при её удалении меняются только атрибуты. Доли оставшихся категорий не перенормируются; знаменатель остаётся «Все категории».', '',
        'ARI усредняем по 24 месяцам. Для Жаккара один раз сопоставляем метки с основной моделью по всем МО-месяцам венгерским алгоритмом; затем считаем пересечение / объединение для каждого типа на всей панели. Это устойчивость состава, не точность по известным истинным типам. Параметр h сохраняется: удаление координаты меняет расстояния и силу сглаживания. Это проверка всей цепочки при фиксированных настройках, не чистый причинный эффект признака.', '',
        '| Удалено | Средний ARI | Жаккар типа 1 | Жаккар типа 2 | Жаккар типа 3 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for row in data['ablations']:
        lines.append('| '+row['name']+' | '+f'{row["ari"]:.3f}'+' | '+' | '.join(f'{p["jaccard"]:.3f}' for p in row['profiles'])+' |')
    weakest = min(data['ablations'],key=lambda r:r['ari'])
    lines += ['', f'Наибольшее изменение среди проверенных удалений: {weakest["name"]}, ARI {weakest["ari"]:.3f}. Высокий ARI означает, что исключённый признак мало меняет разбиение, а не что признак экономически неважен. Низкий ARI не доказывает ошибочность исходной типологии.', '',
        '## Сетка экономических сетей', '',
        f'Проверено {len(data["networks"])} сочетания: расстояния {data["protocol"]["distances"]}, число соседей {data["protocol"]["neighbors"]}, ширины ядра {data["protocol"]["bandwidths"]}. Расстояния считаются по шести стандартизованным признакам расходов. Cosine = 1 − косинус между такими векторами, а не между сырыми долями. Во всех случаях веса exp(−d²/(2h²)), симметризация максимумом, без петель; изоляты сохраняют свои атрибуты. При равных расстояниях порядок соседей может зависеть от реализации sklearn. Численные значения h для разных расстояний не означают одинаковую плотность весов.', '',
        'Во всех вариантах одинаковые K = 3, признаки, 24 месяца, seed и доля окружения. SW, CH и S_Dbw считаются на одних исходных стандартизованных признаках. AVI, AVU и MQ на одной эталонной динамической транспортной сети: они измеряют соответствие ей, а не беспристрастное качество любой сети. MQ = 3 × AVI, AVU = 2/3, поэтому эти показатели не складываем в общий рейтинг. Сводные значения являются средними по месяцам; временной ARI по 23 парам. Средняя степень считает ненулевые рёбра после симметризации.', '',
        '| Расстояние | Соседей | h | SW | S_Dbw | ARI во времени | ARI с основной моделью |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in data['networks']:
        lines.append(f'| {row["distance"]} | {row["neighbors"]} | {row["bandwidth"]} | {row["silhouette"]:.4f} | {row["s_dbw"]:.4f} | {row["temporal_ari"]:.4f} | {row["reference_ari"]:.4f} |')
    best = max(data['networks'],key=lambda r:r['silhouette'])
    lines += ['',f'Лучший SW в этой сетке: {best["silhouette"]:.4f} ({best["distance"]}, k={best["neighbors"]}, h={best["bandwidth"]}); у основной модели {data["baseline"]["silhouette"]:.4f}. Это максимум на тех же данных, а не подтверждённое преимущество на новых наблюдениях. Значимость различий не оценивалась. Выбор лучшего из 24 вариантов даёт преимущество перебору; поэтому итоговую модель автоматически не заменяем.', '',
        'Сетка охватывает два определения расстояния и разные настройки. Она не охватывает корреляции временных рядов, лаговые связи, DTW или обучаемые графы. Удаления признаков не проверяют выбор K и не подтверждают истинность отдельных экономических переходов.', '',
        'Артефакты: `artifacts/research/feature_ablation_monthly.csv`, `feature_ablation_summary.csv`, `network_grid_monthly.csv`, `network_grid_summary.csv`. Машиночитаемые результаты, профили и хеши входов: `site/sensitivity-data.json`.', '']
    for path in [ROOT/'reports/sensitivity.md', ROOT/'site/sensitivity-method.md']:
        path.write_text('\n'.join(lines),encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config()
    protocol = json.loads((ROOT/'config/sensitivity.json').read_text())
    assert protocol['distances'] == ['euclidean','cosine']
    assert set(protocol['drop_together']) <= set(FEATURES) and protocol['drop_together']
    assert all(1 <= k < 2016 for k in protocol['neighbors'])
    assert all(h > 0 for h in protocol['bandwidths'])
    monthly, _ = prepare_monthly()
    ids = sorted(monthly.territory_id.unique()); n = len(ids)
    x = scaled_monthly(monthly)
    graph = transport(ids,config)
    research = json.loads((ROOT/'site/research-data.json').read_text())
    h = research['bandwidth']
    ref = pd.read_csv(ROOT/'artifacts/dynamic/monthly_clusters.csv').sort_values(['date','territory_id']).cluster.to_numpy()
    baseline = transport_representation(x,FEATURES,graph,n,config['neighbor_mix'],h)
    assert adjusted_rand_score(ref,fit_model(baseline,config).labels_) == 1
    ablations, ablation_months = [], []
    for dropped in [[name] for name in FEATURES]+[protocol['drop_together']]:
        columns = [i for i,name in enumerate(FEATURES) if name not in dropped]
        features = [FEATURES[i] for i in columns]
        representation = transport_representation(x[:,columns],features,graph,n,config['neighbor_mix'],h)
        labels = fit_model(representation,config).labels_
        rows, profiles = agreement(ref,labels,n)
        name = ' + '.join(NAMES[f] for f in dropped)
        ablations.append({'name':name,'dropped':dropped,'ari':float(np.mean([r['ari'] for r in rows])),'profiles':profiles})
        ablation_months.extend([{'removed':','.join(dropped),**r} for r in rows])
        print(f'Ablation {name}: {ablations[-1]["ari"]:.4f}',flush=True)
    pd.DataFrame(ablation_months).to_csv(OUT/'feature_ablation_monthly.csv',index=False)
    pd.DataFrame([{'removed':','.join(row['dropped']),'ari':row['ari'],**{f'jaccard_{p["cluster"]}':p['jaccard'] for p in row['profiles']}} for row in ablations]).to_csv(OUT/'feature_ablation_summary.csv',index=False)
    blocks = x.reshape(24,n,-1)
    evaluation = [economic_graph(graph,block[:,:-1],h) for block in blocks]
    for g in evaluation:g.eliminate_zeros()
    cache = {distance:[NearestNeighbors(n_neighbors=max(protocol['neighbors'])+1,metric=distance).fit(block[:,:-1]).kneighbors(block[:,:-1]) for block in blocks] for distance in protocol['distances']}
    network_rows, summaries = [], []
    for distance,k,width in itertools.product(protocol['distances'],protocol['neighbors'],protocol['bandwidths']):
        graphs = [graph_from_neighbors(ds,js,k,width) for ds,js in cache[distance]]
        representation = np.vstack([smooth(block,g,config['neighbor_mix']) for block,g in zip(blocks,graphs)])
        labels = fit_model(representation,config).labels_.reshape(24,n)
        rows = []
        for month,(block,labs,g,eg) in enumerate(zip(blocks,labels,graphs,evaluation)):
            row = {'distance':distance,'neighbors':k,'bandwidth':width,'month':month+1,'silhouette':silhouette_score(block,labs),'ch':calinski_harabasz_score(block,labs),'s_dbw':s_dbw(block,labs),**network_indices(eg,labs),'reference_ari':adjusted_rand_score(ref.reshape(24,n)[month],labs),'temporal_ari':adjusted_rand_score(labels[month-1],labs) if month else None,'mean_degree':g.nnz/n}
            rows.append(row)
        network_rows.extend(rows)
        mean = pd.DataFrame(rows).drop(columns=['distance','neighbors','bandwidth','month']).mean().to_dict()
        summaries.append({'distance':distance,'neighbors':k,'bandwidth':width,**mean})
        print(f'Network {distance} k={k} h={width}: SW {mean["silhouette"]:.4f}',flush=True)
    pd.DataFrame(network_rows).to_csv(OUT/'network_grid_monthly.csv',index=False)
    pd.DataFrame(summaries).to_csv(OUT/'network_grid_summary.csv',index=False)
    inputs = ['config/sensitivity.json','config/dynamic_model.json','site/research-data.json','artifacts/dynamic/monthly_clusters.csv']
    data = {'protocol':protocol,'scope':'base_monthly','clusters':research['clusters'],'ablations':ablations,'networks':summaries,'baseline':next(row for row in research['networks'] if row['model']=='transport_dynamic'),'inputs':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in inputs}}
    (ROOT/'site/sensitivity-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    write_report(data)


if __name__ == '__main__':
    with threadpool_limits(limits=1):main()
