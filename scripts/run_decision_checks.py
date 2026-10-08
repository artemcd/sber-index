"""Cluster-count subsampling and known-truth, retrospective transition checks."""
import hashlib
import json
import platform
import scipy
import sklearn

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from run_baseline import ROOT, FEATURES
from run_dynamic_model import prepare_monthly, scaled_monthly, load_config, representations, fit_model
from run_research import transport, align
from interpret_clusters import persistent_transitions

OUT = ROOT / 'artifacts/research'


def transition_events(labels, margin=None, persistent=True):
    months, nodes = labels.shape
    if not persistent:
        return [(int(i), int(t), int(labels[t-1,i]), int(labels[t,i]))
                for t in range(1,months) for i in np.flatnonzero(labels[t] != labels[t-1])]
    frame = pd.DataFrame({'territory_id':np.tile(np.arange(nodes),months),
                          'date':np.repeat(np.arange(months),nodes),
                          'cluster':labels.ravel(),
                          'relative_margin':np.zeros(labels.size) if margin is None else margin.ravel()})
    frame = frame.sort_values(['territory_id','date'])
    events = persistent_transitions(frame)
    if events.empty:
        return []
    return list(events[['territory_id','date','from_cluster','to_cluster']].itertuples(index=False,name=None))


def score_events(truth, predicted, tolerance):
    real = transition_events(truth,persistent=False)
    matched_true, matched_pred = set(), set()
    pairs = sorted((abs(p[1]-a[1]),i,j) for i,a in enumerate(real) for j,p in enumerate(predicted)
                   if a[0]==p[0] and a[2:]==p[2:] and abs(p[1]-a[1])<=tolerance)
    for _,i,j in pairs:
        if i not in matched_true and j not in matched_pred:
            matched_true.add(i); matched_pred.add(j)
    changed = {a[0] for a in real}
    stable = set(range(truth.shape[1]))-changed
    false_stable = {p[0] for p in predicted if p[0] in stable}
    return {'true_events':len(real),'detected_events':len(predicted),'matched_events':len(matched_true),
            'false_events':len(predicted)-len(matched_pred),
            'precision':len(matched_pred)/len(predicted) if predicted else None,
            'recall':len(matched_true)/len(real) if real else None,
            'stable_nodes':len(stable),'false_stable_nodes':len(false_stable),
            'false_stable_percent':100*len(false_stable)/len(stable) if stable else None}


def calibration(x, labels):
    centers = np.array([x[labels==c].mean(axis=0) for c in range(3)])
    residuals = (x-centers[labels]).reshape(24,-1,len(FEATURES))
    effects = residuals.mean(axis=0)
    noise = residuals-effects
    return centers, np.cov(effects,rowvar=False), np.cov(noise.reshape(-1,len(FEATURES)),rowvar=False)


def generate(centers, effect_cov, noise_cov, protocol, scenario, run):
    rng = np.random.default_rng(protocol['seed']+run)
    n = protocol['synthetic_nodes']
    initial = rng.permutation(np.arange(n)%3)
    truth = np.tile(initial,(24,1))
    count = int(n*protocol['change_fraction'])
    order = rng.permutation(n)
    if scenario['changes']:
        selected = order[:count]
        truth[protocol['change_month']:,selected] = (initial[selected]+rng.integers(1,3,count))%3
    effects = rng.multivariate_normal(np.zeros(len(FEATURES)),effect_cov,size=n)
    noise = rng.multivariate_normal(np.zeros(len(FEATURES)),noise_cov,size=(24,n))
    x = centers[truth] + scenario['effects']*effects + scenario['noise']*noise
    if scenario['spike']:
        selected = order[count:2*count]
        x[5,selected] += centers[(initial[selected]+1)%3]-centers[initial[selected]]
    # Market access is a fixed input in the real model, even when a synthetic type changes.
    x[:,:, -1] = centers[initial,-1]+scenario['effects']*effects[:,-1]
    x = StandardScaler().fit_transform(x.reshape(-1,len(FEATURES)))
    same = initial[:,None] == initial[None,:]
    within = protocol['expected_degree']*protocol['within_edge_share']/(n/3-1)
    between = protocol['expected_degree']*(1-protocol['within_edge_share'])/(2*n/3)
    upper = np.triu(rng.random((n,n)) < np.where(same,within,between),1)
    weights = upper*rng.uniform(.2,1,(n,n))
    graph = sparse.csr_matrix(weights+weights.T)
    return x, graph, truth


def fit_with_margin(x, config):
    model = fit_model(x,config)
    distances = np.sort(model.transform(x),axis=1)
    margin = (distances[:,1]-distances[:,0])/(distances[:,1]+1e-12)
    return model.labels_, margin


def check_counts(monthly, missing, x, dynamic, config, h, protocol):
    ids = sorted(monthly.territory_id.unique())
    n = len(ids)
    full, rows, sample_rows = {}, [], []
    for k in protocol['cluster_counts']:
        labels = fit_model(dynamic,{**config,'clusters':k}).labels_
        full[k] = labels
        blocks = labels.reshape(24,n)
        row = {'k':k,'silhouette':float(np.mean([silhouette_score(a,b) for a,b in zip(x.reshape(24,n,-1),blocks)])),
               'temporal_ari':float(np.mean([adjusted_rand_score(a,b) for a,b in zip(blocks[:-1],blocks[1:])])),
               'min_monthly_share':float(min(np.bincount(b,minlength=k).min()/n for b in blocks))}
        rows.append(row)
        print(f'Full monthly model K={k}',flush=True)
    ref = pd.read_csv(ROOT/'artifacts/dynamic/monthly_clusters.csv').sort_values(['date','territory_id']).cluster.to_numpy()
    assert adjusted_rand_score(ref,full[config['clusters']]) == 1
    rng = np.random.default_rng(protocol['seed'])
    for run in range(protocol['subsamples']):
        chosen = np.sort(rng.choice(n,int(n*protocol['sample_fraction']),replace=False))
        selected_ids = [ids[i] for i in chosen]
        frame = monthly[monthly.territory_id.isin(selected_ids)].copy()
        frame['relative_spend'] = np.log(frame['Все категории']/frame.groupby('date')['Все категории'].transform('median'))
        mask = frame.territory_id.isin(missing)
        frame.loc[mask,'market_access'] = frame.loc[~mask,'market_access'].median()
        frame['log_market_access'] = np.log(frame.market_access)
        subx = scaled_monthly(frame)
        _, subdynamic, _ = representations(subx,transport(selected_ids,config),len(chosen),config['neighbor_mix'],h)
        for k in protocol['cluster_counts']:
            labels = fit_model(subdynamic,{**config,'clusters':k}).labels_
            reference = full[k].reshape(24,n)[:,chosen].ravel()
            aligned = align(reference,labels)
            jaccards = [np.sum((reference==c)&(aligned==c))/np.sum((reference==c)|(aligned==c)) for c in np.unique(reference)]
            sample_rows.append({'k':k,'run':run+1,'mean_monthly_ari':np.mean([adjusted_rand_score(a,b) for a,b in zip(reference.reshape(24,-1),labels.reshape(24,-1))]),'min_cluster_jaccard':min(jaccards)})
        print(f'K-count subsample {run+1}/{protocol["subsamples"]}',flush=True)
    samples = pd.DataFrame(sample_rows)
    for row in rows:
        values = samples[samples.k==row['k']]
        row.update({'subsample_ari_median':float(values.mean_monthly_ari.median()),'subsample_ari_min':float(values.mean_monthly_ari.min()),'subsample_ari_max':float(values.mean_monthly_ari.max()),'min_jaccard_median':float(values.min_cluster_jaccard.median())})
    pd.DataFrame(rows).to_csv(OUT/'cluster_count_checks.csv',index=False)
    samples.to_csv(OUT/'cluster_count_subsamples.csv',index=False)
    two = align(np.where(ref==3,1,0),full[2]).reshape(24,n)[-1]
    # The contingency has arbitrary K=2 column names; its counts are invariant to that choice.
    contingency = [{'reference_type':int(c),'two_type':int(d),'count':int(np.sum((ref[-n:]==c)&(two==d)))} for c in [1,2,3] for d in [0,1]]
    return rows, contingency, full[3]


def synthetic_checks(x, labels, config, h, protocol):
    centers, effects, noise = calibration(x,labels)
    rows = []
    for scenario in protocol['scenarios']:
        for run in range(protocol['synthetic_runs']):
            sx, graph, truth = generate(centers,effects,noise,protocol,scenario,run)
            _, dynamic, _ = representations(sx,graph,protocol['synthetic_nodes'],config['neighbor_mix'],h)
            for method,features in [('attributes',sx),('dynamic',dynamic)]:
                candidate, margin = fit_with_margin(features,config)
                predicted = align(truth.ravel(),candidate).reshape(truth.shape)
                for rule in ['all','persistent']:
                    events = transition_events(predicted,margin.reshape(truth.shape),persistent=rule=='persistent')
                    rows.append({'scenario':scenario['id'],'run':run+1,'model':method,'rule':rule,'ari':np.mean([adjusted_rand_score(a,b) for a,b in zip(truth,predicted)]),**score_events(truth,events,protocol['event_tolerance'])})
            print(f'Synthetic {scenario["id"]} {run+1}/{protocol["synthetic_runs"]}',flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT/'synthetic_transition_runs.csv',index=False)
    summary = []
    for (scenario,model,rule),group in frame.groupby(['scenario','model','rule']):
        true, detected, matched = group[['true_events','detected_events','matched_events']].sum()
        summary.append({'scenario':scenario,'model':model,'rule':rule,'ari':float(group.ari.mean()),'precision':float(matched/detected) if detected else None,'recall':float(matched/true) if true else None,'false_stable_percent':float(100*group.false_stable_nodes.sum()/group.stable_nodes.sum()),'matched_events':int(matched),'true_events':int(true),'detected_events':int(detected),'false_events':int(detected-matched)})
    pd.DataFrame(summary).to_csv(OUT/'synthetic_transition_summary.csv',index=False)
    return summary, {'centers':centers.tolist(),'effect_std':np.sqrt(np.diag(effects)).tolist(),'noise_std':np.sqrt(np.diag(noise)).tolist()}


def synthetic_conclusion(data):
    rows = {(r['scenario'],r['rule']):r for r in data['synthetic'] if r['model']=='dynamic'}
    raw, filtered = rows[('calibrated','all')], rows[('calibrated','persistent')]
    null = rows[('no_changes','persistent')]
    return f'В сценарии с масштабом реальных остатков фильтр снижает ложные сигналы у стабильных узлов с {raw["false_stable_percent"]:.1f}% до {filtered["false_stable_percent"]:.1f}%, но находит {100*filtered["recall"]:.1f}% настоящих смен. Среди найденных событий верны {100*filtered["precision"]:.1f}%. В сценарии без настоящих смен ложный сигнал остаётся у {null["false_stable_percent"]:.1f}% узлов. Фильтр полезен, но не гарантирует достоверность и пропускает часть событий.'


def write_report(data):
    p = data['protocol']
    lines = ['# Число типов и проверка переходов', '',
        'Проверяется основная помесячная типология. Исследование не меняет назначения на карте и не относится к варианту с населением и четырьмя типами.', '',
        '## Запуск', '',
        '`make decisions` повторяет оба опыта на CPU. Они также входят в `make research` и полный `make all`. Нужны исходные файлы СберИндекса, назначения основной модели, подбор h и готовый `site/data.json`. Параметры заданы до расчёта в `config/decision_checks.json`; параметры модели в `config/dynamic_model.json`. Новых данных и зависимостей нет. Таблицы в `artifacts/research/`, JSON с конфигурацией, калибровкой и хешами входов в `site/decision-data.json`.', '',
        '## 1. Число типов: одинаковая проверка для каждого K', '',
        f'Для K = {p["cluster_counts"]} обучаем общие центры на всех 24 месяцах. Фиксированы признаки, h, транспортная сеть, доля окружения, n_init и seed KMeans. SW оцениваем на исходных стандартизованных признаках; ARI во времени по 23 соседним парам. Минимальная доля берётся по всем группам и месяцам.', '',
        f'Затем используем {p["subsamples"]} одинаковых случайных подвыборок по {p["sample_fraction"]:.0%} территорий для всех K, seed {p["seed"]}. В каждой заново считаем месячные медианы, заполнение доступности, StandardScaler, ближайших транспортных соседей, масштабы расстояний, экономические веса и центры. Сравнение только на общих территориях с полной моделью того же K. Метки для Жаккара сопоставлены один раз по всей панели; ARI от меток не зависит. Диапазон повторений не доверительный интервал.', '',
        '| K | SW | ARI во времени | Медиана ARI подвыборок | Диапазон | Медиана минимального Жаккара | Мин. доля |',
        '| ---: | ---: | ---: | ---: | --- | ---: | ---: |']
    for r in data['cluster_counts']:
        lines.append(f'| {r["k"]} | {r["silhouette"]:.4f} | {r["temporal_ari"]:.4f} | {r["subsample_ari_median"]:.4f} | {r["subsample_ari_min"]:.4f}–{r["subsample_ari_max"]:.4f} | {r["min_jaccard_median"]:.4f} | {r["min_monthly_share"]:.1%} |')
    lines += ['', 'Число групп не выбираем автоматически по одной метрике. K = 2 может быть устойчивее, но объединять содержательно разные профили; при увеличении K появляются более мелкие группы. Устойчивость означает воспроизводимость выбранного разбиения, не существование истинного числа экономических типов. Полные назначения K = 3 должны воспроизводить текущую карту с ARI = 1.', '',
        'Состав двух групп относительно трёх текущих типов в декабре 2024:', '',
        '| Текущий тип | Группа K=2 | Территорий |', '| ---: | ---: | ---: |']
    for r in data['two_type_contingency']:
        lines.append(f'| {r["reference_type"]} | {r["two_type"]+1} | {r["count"]} |')
    lines += ['', 'Артефакты: `cluster_count_checks.csv`, `cluster_count_subsamples.csv`.', '',
        '## 2. Синтетические изменения с известной истиной', '',
        f'Генератор: {p["synthetic_nodes"]} узлов, три исходные группы одинакового размера, 24 месяца. В сценариях со сменами {p["change_fraction"]:.0%} узлов меняют истинную группу с месяца {p["change_month"]+1} и остаются в ней до конца. {p["synthetic_runs"]} seed на сценарий. Узлы не меняют группу в контрольном сценарии. В опыте с разовым скачком отдельные {p["change_fraction"]:.0%} узлов получают смещение признаков к другому центру на один месяц, но истинный тип не меняется.', '',
        'Центры взяты из исходных стандартизованных признаков основной модели. Остаток от центра разделён на постоянное отклонение узла (среднее за 24 месяца) и месячное отклонение. Из их эмпирических ковариаций генерируем гауссовские эффекты и шум. В сценарии «масштаб реальных остатков» их множители равны 1; это калибровка масштаба, а не доказательство правильности генератора. Доступность рынков фиксирована для узла во всех месяцах, как в основной модели. Синтетические признаки снова стандартизируются на всей панели.', '',
        f'Кандидатная сеть является взвешенной стохастической блочной моделью по исходным группам, а не моделью реальных дорог. Ожидаемая степень {p["expected_degree"]}, доля внутригрупповых связей {p["within_edge_share"]:.0%}, вес каждого ребра равномерный от 0.2 до 1. Топология не меняется после истинной смены. Экономические веса и смешивание признаков вычисляются теми же функциями, h и долей окружения, что в финальной модели. Истинные метки участвуют только в генерации и оценке, не передаются KMeans.', '',
        'Сравниваем KMeans по признакам и текущую динамическую сетевую модель. Для каждого считаем все соседние смены и фильтр из `interpret_clusters.persistent_transitions`: предыдущая и новая непрерывные серии не короче трёх месяцев. Используем ту же функцию, которой получены 215 переходов на карте. В оценке глобально сопоставляем метки предсказания и истины.', '',
        f'Истинное и найденное события сопоставляются один к одному при совпадении узла, направления и дате в пределах ±{p["event_tolerance"]} месяцев. Precision = доля найденных событий, совпавших с истиной; recall = доля истинных событий, найденных моделью. Ложный сигнал у стабильного узла = хотя бы одно найденное событие у узла без настоящей смены. В таблице события суммируются по seed перед расчётом precision/recall; ARI усреднён по месяцам и seed. Если знаменатель нулевой, показатель не определён (пустое значение), а не равен 100%.', '',
        '| Сценарий | Модель | Фильтр | ARI | Precision | Recall | Стабильных узлов с ложной сменой, % |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    names = {s['id']:s['name'] for s in p['scenarios']}
    percent = lambda value: 'нет оценки' if value is None else f'{100*value:.1f}%'
    for r in data['synthetic']:
        lines.append(f'| {names[r["scenario"]]} | {r["model"]} | {r["rule"]} | {r["ari"]:.3f} | {percent(r["precision"])} | {percent(r["recall"])} | {r["false_stable_percent"]:.1f} |')
    lines += ['', 'Это ретроспективный опыт: центры обучены сразу на всех 24 месяцах, фильтр использует продолжительность последующей серии. Допуск по дате не является задержкой обнаружения в реальном времени. Синтетика проверяет этап кластеризации и извлечения событий после подготовки признаков, не чтение исходных таблиц или ОКТМО. Гауссовские ошибки и блочная сеть не охватывают все реальные ошибки, сезонность, изменения границ и региональные шоки. Ковариации остатков основной модели могут содержать реальные изменения и не являются чистым измерительным шумом. Нельзя переносить precision/recall на 215 реальных событий.', '',
        synthetic_conclusion(data), '',
        'Устойчивая последовательность назначений сама по себе не доказывает экономическое событие. Проверенные настройки не подбирались по результату синтетики. Гауссовский генератор и заданная доля смен влияют на оценку precision, поэтому эти числа не являются оценкой доли верных событий в реальной карте.', '',
        'Артефакты: `synthetic_transition_runs.csv`, `synthetic_transition_summary.csv`. Значения seed, версии Python и библиотек, параметры и хеши кода в JSON. На лендинге оставлены две компактные визуализации; подробности находятся в этом отчёте.', '']
    text = '\n'.join(lines)
    (ROOT/'reports/decision_checks.md').write_text(text)
    (ROOT/'site/decision-method.md').write_text(text)


def main():
    config = load_config()
    protocol = json.loads((ROOT/'config/decision_checks.json').read_text())
    assert protocol['synthetic_nodes'] >= 30 and protocol['synthetic_nodes']%3==0
    assert 3 <= protocol['change_month'] <= 21 and protocol['event_tolerance'] >= 0
    assert 0 < protocol['sample_fraction'] < 1 and 0 < protocol['within_edge_share'] < 1
    assert protocol['cluster_counts'] == sorted(set(protocol['cluster_counts'])) and 2 in protocol['cluster_counts'] and 3 in protocol['cluster_counts']
    assert 0 < protocol['change_fraction'] <= .5
    OUT.mkdir(parents=True,exist_ok=True)
    monthly,missing = prepare_monthly()
    x = scaled_monthly(monthly)
    n = monthly.territory_id.nunique()
    sensitivity = pd.read_csv(ROOT/'artifacts/dynamic/bandwidth_sensitivity.csv')
    eligible = sensitivity.query('month_to_month_stability >= .95 and min_monthly_cluster_share >= .15')
    h = float(eligible.loc[eligible.silhouette.idxmax(),'economic_bandwidth'])
    _,dynamic,_ = representations(x,transport(sorted(monthly.territory_id.unique()),config),n,config['neighbor_mix'],h)
    counts,contingency,labels = check_counts(monthly,missing,x,dynamic,config,h,protocol)
    synthetic,calibrated = synthetic_checks(x,labels,config,h,protocol)
    inputs = ['config/decision_checks.json','config/dynamic_model.json','artifacts/dynamic/bandwidth_sensitivity.csv','artifacts/dynamic/monthly_clusters.csv','site/data.json','scripts/run_decision_checks.py','scripts/run_baseline.py','scripts/run_dynamic_model.py','scripts/run_graph_model.py','scripts/run_research.py','scripts/interpret_clusters.py']
    data = {'scope':'base_monthly','protocol':protocol,'cluster_counts':counts,'two_type_contingency':contingency,'synthetic':synthetic,'calibration':calibrated,'bandwidth':h,'runtime':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__},'inputs':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in inputs}}
    (ROOT/'site/decision-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    write_report(data)
    print(json.dumps({'counts':counts,'synthetic':synthetic},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
