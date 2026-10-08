"""Retrospective checks of the saved monthly model; no model selection on Rosstat."""
import hashlib
import json

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from sklearn.linear_model import Ridge
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, silhouette_score
from sklearn.model_selection import KFold
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from run_baseline import ROOT
from run_dynamic_model import load_config, prepare_monthly, scaled_monthly, representations, fit_model
from run_graph_model import transport_graph, normalized
from compare_models import s_dbw, network_indices

OUT = ROOT / 'artifacts/research'


def align(reference, labels):
    old, new = np.unique(reference), np.unique(labels)
    counts = np.array([[np.sum((reference == a) & (labels == b)) for b in new] for a in old])
    a, b = linear_sum_assignment(-counts)
    mapping = dict(zip(new[b], old[a]))
    return np.array([mapping[x] for x in labels])


def transport(ids, config):
    road, _ = transport_graph(ids, 'highway', config['highway_neighbors'])
    rail, _ = transport_graph(ids, 'railway', config['railway_neighbors'])
    return (road + config['rail_weight'] * rail).tocsr()


def economic_knn(block, neighbors, bandwidth):
    # Ask for one extra neighbor, then explicitly remove self, including tied points.
    distances, indices = NearestNeighbors(n_neighbors=neighbors + 1).fit(block).kneighbors(block)
    edges = [(i, j, d) for i, (js, ds) in enumerate(zip(indices, distances))
             for j, d in list(zip(js[js != i], ds[js != i]))[:neighbors]]
    rows, cols, ds = np.array(edges).T
    graph = sparse.csr_matrix((np.exp(-ds**2 / (2 * bandwidth**2)), (rows.astype(int), cols.astype(int))), shape=(len(block), len(block)))
    graph = graph.maximum(graph.T)
    graph.eliminate_zeros()
    return graph


def write_report(data):
    r = data['robustness']
    names = {'attributes':'Только показатели','transport_static':'Транспортная сеть','transport_dynamic':'Динамическая сеть','economic_knn':'Экономические соседи'}
    lines = [
        '# Проверки финальной помесячной типологии',
        '',
        'Объект проверки: основная модель, 2016 муниципалитетов, январь 2023 по декабрь 2024, K = 3. Эти результаты не относятся к модели с населением и четырьмя типами.',
        '',
        '## Воспроизведение',
        '',
        '`make research` использует исходные файлы СберИндекса и уже построенные `site/data.json`, `site/rosstat-data.json`, `artifacts/external/population_annual.csv`, а также назначения и подбор h в `artifacts/dynamic/`. После замены исходников сначала выполните `make all`. Конфигурация: `config/research.json`, параметры основной модели: `config/dynamic_model.json`. Все вычисления на CPU, один поток. Хеши входных артефактов сохранены в `site/research-data.json`.',
        '',
        '## 1. Устойчивость к составу территорий',
        '',
        'Сначала повторное обучение должно воспроизвести сохранённую помесячную разметку с ARI = 1. Затем 20 раз без возвращения выбираем 80% территорий (1612), сохраняя все их месяцы. Заново вычисляем месячные медианы расходов и долей, заполнение пропусков доступности и StandardScaler. Транспортные соседи и масштабы расстояний пересчитываются на выбранных территориях; заново обучаются центры KMeans. K, h, число соседей, вес сглаживания и seed KMeans фиксированы. Seed отбора территорий: 202410.',
        '',
        'Сравниваем с исходными назначениями только на выбранных территориях. ARI не зависит от номеров кластеров. Для доли совпадений одну общую перестановку меток выбираем венгерским алгоритмом по всем 24 месяцам, не отдельно для каждого месяца.',
        '',
        f'Медиана среднего по месяцам ARI: **{r["median"]:.4f}**. Диапазон между повторениями: **{r["min"]:.4f}–{r["max"]:.4f}**. Это диапазон чувствительности, не доверительный интервал. Все 480 оценок: `artifacts/research/subsamples.csv`.',
        '',
        'Проверка подтверждает воспроизводимость групп при удалении части территорий. Она не обосновывает единственность K = 3, не проверяет другие годы, ошибки исходных измерений или структурное выпадение целого региона.',
        '',
        '## 2. Альтернативная сеть',
        '',
        'Сравниваем KMeans без сети, со статической транспортной сетью, с динамической транспортной сетью и с динамической экономической kNN-сетью. В последней восемь ближайших соседей по евклидовому расстоянию в шести стандартизованных признаках расходов выбираются заново каждый месяц независимо от географии. Граф симметризуется максимумом весов; вес exp(−d²/(2h²)), h совпадает с основной моделью. Во всех сетевых вариантах доля окружения 0.2; K = 3, n_init = 30, seed = 42. Изолированная вершина сохраняет собственные признаки.',
        '',
        'Все варианты оцениваются на одном пространстве исходных стандартизованных признаков. Сетевые индексы считаются на одной динамической транспортной сети, поэтому отражают согласованность именно с ней. Усредняем по 24 месяцам; temporal ARI по 23 соседним парам. Полная таблица: `artifacts/research/networks.csv`.',
        '',
        '| Вариант | SW ↑ | CH ↑ | S_Dbw ↓ | AVI ↑ | AVU ↓ | MQ ↑ | ARI между месяцами ↑ |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for row in data['networks']:
        lines.append(f'| {names[row["model"]]} | {row["silhouette"]:.4f} | {row["ch"]:.1f} | {row["s_dbw"]:.4f} | {row["avi"]:.4f} | {row["avu"]:.4f} | {row["mq"]:.4f} | {row["temporal_ari"]:.4f} |')
    lines += ['', 'Динамическая транспортная сеть выигрывает по SW и временной устойчивости. Экономическая kNN-сеть лучше по S_Dbw, статическая транспортная по AVI. Разница SW между транспортными вариантами всего 0.0021; статистическая значимость не установлена. Это компромисс, а не превосходство по всем критериям. В этой таблице приведена одна опорная конфигурация экономической сети. Расширение до 24 настроек и удаление признаков описаны отдельно в `reports/sensitivity.md` (`make sensitivity`).', '', 'В текущей реализации MQ = K × AVI. При K = 3 на недегенеративном неориентированном графе AVU = 2/3: знаменатель каждого парного слагаемого равен общей массе межкластерных рёбер. Эти индексы не являются независимыми свидетельствами качества.', '', '## 3. Независимые показатели Росстата', '', 'Для каждого показателя оставляем только территории с допустимыми значениями за оба года по правилам `reports/rosstat_context.md`. Доходы, жильё и инвестиции не входят в обучение типов. Тип берём на декабрь соответствующего года. Цель регрессии: log(1 + показатель на жителя); денежные величины измерены в тыс. рублей, жильё в м². Население на 1 января, денежные значения номинальные.', '', 'Базовая Ridge-регрессия: one-hot региона и стандартизованный log(население). Расширенная: те же признаки плюс one-hot типа. Alpha = 1, без подбора. Пять случайных folds по территориям, seed = 202410, одни и те же разбиения для двух моделей и обоих лет внутри показателя. Encoder и scaler обучаются только внутри train. Каждая территория получает один прогноз вне обучающей выборки. Итоговая MSE рассчитана по всем таким прогнозам, не как невзвешенное среднее folds. Эффект = 100 × (1 − MSE_с_типом / MSE_базовая).', '', '| Показатель | Год | Территорий | Снижение MSE, % |', '| --- | ---: | ---: | ---: |']
    for row in data['external']:
        lines.append(f'| {row["metric"]} | {row["year"]} | {row["n"]} | {row["mse_reduction_percent"]:.2f} |')
    lines += ['', 'Вывод: в этой проверке тип добавляет информацию о доходах и строительстве сверх региона и населения; связь с инвестициями заметно слабее. В 2024 году медиана ввода жилья в крупных центрах около 0.94 м² на жителя, в двух других типах около 0.26–0.27. Это описательные медианы доступной выборки, без поправок; скорректированное сравнение выполнено отдельно регрессиями.', '', 'Ограничения: типология обучена на всём двухлетнем наборе признаков (включая проверяемые территории), но без целевых показателей Росстата. Это внешняя ретроспективная проверка связи, не полностью изолированное обучение всей цепочки и не прогноз на новые территории или годы. Случайные folds не исключают пространственную зависимость; значимость и доверительные интервалы не оценивались. Результат зависит от спецификации базовой регрессии. Пропуски Росстата не случайны: например, доходы хуже покрывают крупные центры. Инвестиции исключают малый бизнес. Различия не устанавливают причинность.', '', 'По folds: `artifacts/research/external_folds.csv`. Сводка: `artifacts/research/external_validation.csv`. Медианы и численность каждой группы: `site/research-data.json`.', '']
    (ROOT/'reports/research.md').write_text('\n'.join(lines))
    (ROOT/'site/research-method.md').write_text('\n'.join(lines))


def main():
    config = load_config()
    protocol = json.loads((ROOT / 'config/research.json').read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    monthly, missing_ids = prepare_monthly()
    ids = sorted(monthly.territory_id.unique())
    dates = sorted(monthly.date.astype(str).unique())
    n = len(ids)
    sensitivity = pd.read_csv(ROOT / 'artifacts/dynamic/bandwidth_sensitivity.csv')
    eligible = sensitivity.query('month_to_month_stability >= .95 and min_monthly_cluster_share >= .15')
    bandwidth = float(eligible.loc[eligible.silhouette.idxmax(), 'economic_bandwidth'])
    x = scaled_monthly(monthly)
    graph = transport(ids, config)
    static, dynamic, graphs = representations(x, graph, n, config['neighbor_mix'], bandwidth)
    reference = pd.read_csv(ROOT / 'artifacts/dynamic/monthly_clusters.csv').sort_values(['date', 'territory_id']).cluster.to_numpy()
    labels = fit_model(dynamic, config).labels_
    assert adjusted_rand_score(reference, labels) == 1, 'Saved monthly model no longer reproduces'
    rng = np.random.default_rng(protocol['seed'])
    robustness = []
    print('Reference reproduced; starting subsamples', flush=True)
    for trial in range(protocol['subsamples']):
        chosen = np.sort(rng.choice(n, int(n * protocol['sample_fraction']), replace=False))
        selected_ids = [ids[i] for i in chosen]
        frame = monthly[monthly.territory_id.isin(selected_ids)].copy()
        frame["relative_spend"] = np.log(frame["Все категории"] / frame.groupby("date")["Все категории"].transform("median"))
        missing = frame.territory_id.isin(missing_ids)
        frame.loc[missing, "market_access"] = frame.loc[~missing, "market_access"].median()
        frame["log_market_access"] = np.log(frame.market_access)
        subx = scaled_monthly(frame)
        _, subdynamic, _ = representations(subx, transport(selected_ids, config), len(chosen), config['neighbor_mix'], bandwidth)
        predicted = fit_model(subdynamic, config).labels_
        expected = reference.reshape(24, n)[:, chosen].ravel()
        aligned = align(expected, predicted)
        for month, (a, b) in enumerate(zip(expected.reshape(24, -1), aligned.reshape(24, -1))):
            robustness.append({'trial': trial + 1, 'date': dates[month], 'ari': adjusted_rand_score(a, b), 'agreement': np.mean(a == b)})
        print(f'Subsample {trial + 1}/{protocol["subsamples"]}', flush=True)
    robust = pd.DataFrame(robustness)
    robust.to_csv(OUT / 'subsamples.csv', index=False)
    economic = []
    for block in x.reshape(24, n, -1):
        g = economic_knn(block[:, :-1], protocol['economic_neighbors'], bandwidth)
        neighbors = normalized(g) @ block
        isolated = np.asarray(g.sum(axis=1)).ravel() == 0
        neighbors[isolated] = block[isolated]
        economic.append((1-config['neighbor_mix'])*block + config['neighbor_mix']*neighbors)
    variants = {'attributes': x, 'transport_static': static, 'transport_dynamic': dynamic, 'economic_knn': np.vstack(economic)}
    rows = []
    for name, features in variants.items():
        assignment = fit_model(features, config).labels_.reshape(24, n)
        for month, (block, labs, evaluation_graph) in enumerate(zip(x.reshape(24,n,-1), assignment, graphs)):
            evaluation_graph.eliminate_zeros()
            row = {'model': name, 'date': dates[month], 'silhouette': silhouette_score(block, labs), 'ch': calinski_harabasz_score(block,labs), 's_dbw': s_dbw(block,labs), **network_indices(evaluation_graph,labs)}
            row['temporal_ari'] = adjusted_rand_score(assignment[month-1],labs) if month else None
            rows.append(row)
        print(f'Network evaluated: {name}', flush=True)
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / 'networks.csv', index=False)
    site = json.loads((ROOT / 'site/data.json').read_text())
    context = json.loads((ROOT / 'site/rosstat-data.json').read_text())
    lookup = {m['id']: m for m in site['municipalities']}
    pop = pd.read_csv(ROOT / 'artifacts/external/population_annual.csv').set_index(['territory_id','year']).population
    validation, folds = [], []
    for metric in ['income','housing','investment']:
        panel = [m for m in context['municipalities'] if all(v is not None for v in m[metric]) and m['id'] in lookup]
        for year_index, year in enumerate(context['years']):
            frame = pd.DataFrame([{'id':m['id'], 'region':lookup[m['id']]['region'], 'cluster':lookup[m['id']]['trajectory'][11 + 12*year_index], 'population':pop.loc[(m['id'],year)], 'value':m[metric][year_index]} for m in panel]).sort_values('id').reset_index(drop=True)
            y = np.log1p(frame.value.to_numpy())
            predictions = np.zeros((2,len(frame)))
            for fold, (train, test) in enumerate(KFold(protocol['folds'], shuffle=True, random_state=protocol['seed']).split(frame)):
                population = StandardScaler().fit(np.log(frame.loc[train,['population']]))
                for version, categories in enumerate([['region'],['region','cluster']]):
                    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False).fit(frame.loc[train,categories])
                    train_x = np.column_stack([population.transform(np.log(frame.loc[train,['population']])), encoder.transform(frame.loc[train,categories])])
                    test_x = np.column_stack([population.transform(np.log(frame.loc[test,['population']])), encoder.transform(frame.loc[test,categories])])
                    predictions[version,test] = Ridge(alpha=protocol['ridge_alpha']).fit(train_x,y[train]).predict(test_x)
                folds.append({'metric':metric,'year':year,'fold':fold+1,'n':len(test),'baseline_mse':np.mean((y[test]-predictions[0,test])**2),'type_mse':np.mean((y[test]-predictions[1,test])**2)})
            mse = np.mean((predictions-y)**2,axis=1)
            validation.append({'metric':metric,'year':year,'n':len(frame),'baseline_rmse_log':np.sqrt(mse[0]),'type_rmse_log':np.sqrt(mse[1]),'mse_reduction_percent':100*(1-mse[1]/mse[0]),'profiles':[{'cluster':int(c),'n':len(group),'median':float(group.value.median())} for c,group in frame.groupby('cluster')]})
    pd.DataFrame(folds).to_csv(OUT/'external_folds.csv',index=False)
    pd.DataFrame([{k:v for k,v in row.items() if k != 'profiles'} for row in validation]).to_csv(OUT/'external_validation.csv',index=False)
    summary = metrics.groupby('model').mean(numeric_only=True).reset_index().to_dict('records')
    trial_means = robust.groupby('trial').ari.mean()
    payload = {'protocol':protocol,'bandwidth':bandwidth,'scope':'base_monthly','clusters':site['clusters'],'robustness':{'median':float(trial_means.median()),'min':float(trial_means.min()),'max':float(trial_means.max()),'runs':trial_means.tolist(),'monthly':robust.groupby('date').ari.agg(['median','min','max']).reset_index().to_dict('records')},'networks':summary,'external':validation,'inputs':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in [ROOT/'config/dynamic_model.json', ROOT/'config/research.json', ROOT/'site/data.json', ROOT/'artifacts/dynamic/monthly_clusters.csv', ROOT/'site/rosstat-data.json',ROOT/'artifacts/external/population_annual.csv']}}
    (ROOT/'site/research-data.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    write_report(payload)
    print(json.dumps({'robustness':payload['robustness'],'networks':summary,'external':validation},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
