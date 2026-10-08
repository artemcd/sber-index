(() => {
  if (!document.querySelector('#research-features')) return;
  const f = (value, digits=3) => Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  const colors = ['#159d87','#ba710f','#8063ce'];
  fetch('sensitivity-data.json').then(r=>{if(!r.ok) throw new Error('Нет файла результатов');return r.json();}).then(data=>{
    const select = document.querySelector('#ablation-feature');
    select.innerHTML = data.ablations.map((r,i)=>`<option value="${i}">${r.name}</option>`).join('');
    select.value = String(data.ablations.findIndex(r=>r.dropped.length===1 && r.dropped[0]==='marketplace_share'));
    function ablations() {
      const chosen = Number(select.value);
      document.querySelector('#ablation-chart').innerHTML = `<svg viewBox="0 0 1100 440" role="img" aria-label="Сходство типов после удаления признаков"><text x="590" y="24">Средний ARI с основной моделью</text>${data.ablations.map((r,i)=>`<text x="0" y="${64+i*45}">${r.name}</text><rect x="590" y="${46+i*45}" width="${r.ari*390}" height="26" fill="${i===chosen?'#159d87':'#a9b8d0'}"/><text x="${600+r.ari*390}" y="${64+i*45}">${f(r.ari)}</text>`).join('')}<text x="590" y="425">0</text><text x="980" y="425" text-anchor="end">1: полное совпадение</text></svg>`;
      const row = data.ablations[chosen];
      document.querySelector('#ablation-profiles').innerHTML = row.profiles.map(p=>`<div style="--profile-color:${colors[p.cluster-1]}"><span>${data.clusters.find(c=>c.id===p.cluster).name}</span><strong>${f(p.jaccard)}</strong><small>Жаккар состава за 24 месяца<br>В декабре: ${p.reference_count_december} → ${p.count_december} территорий</small></div>`).join('');
      const weakest = row.profiles.reduce((a,b)=>a.jaccard<b.jaccard?a:b);
      document.querySelector('#ablation-finding').textContent = `Без «${row.name}» средний ARI равен ${f(row.ari)}. Сильнее всего меняется состав типа «${data.clusters.find(c=>c.id===weakest.cluster).name}»: Жаккар ${f(weakest.jaccard)}. Это чувствительность модели, а не доказательство причинной роли показателя в экономике.`;
    }
    select.addEventListener('change',ablations); ablations();
    const distance = document.querySelector('#grid-distance');
    const metric = document.querySelector('#grid-metric');
    let chosen = null;
    function detail(row) {
      chosen = row;
      document.querySelector('#grid-detail').textContent = `Соседей ${row.neighbors}, h = ${f(row.bandwidth,1)}: SW ${f(row.silhouette)}, CH ${f(row.ch,1)}, S_Dbw ${f(row.s_dbw)}, AVI ${f(row.avi)}, AVU ${f(row.avu)}, MQ ${f(row.mq)}. ARI между месяцами ${f(row.temporal_ari)}, с основной моделью ${f(row.reference_ari)}. Средняя степень сети ${f(row.mean_degree,1)}.`;
      document.querySelectorAll('#network-grid button').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.k)===row.neighbors && Number(button.dataset.h)===row.bandwidth)));
    }
    function grid() {
      const rows = data.networks.filter(r=>r.distance===distance.value);
      const key = metric.value;
      const values = rows.map(r=>r[key]); const min = Math.min(...values), max = Math.max(...values);
      document.querySelector('#grid-baseline').textContent = `Основная динамическая транспортная модель: ${key==='reference_ari'?'1,000':f(data.baseline[key],key==='ch'?1:3)}. ${key==='reference_ari'?'Здесь измеряем сходство разбиений, а не качество.':'Сравните с каждым вариантом ниже.'}`;
      const root = document.querySelector('#network-grid');
      root.innerHTML = `<span>Соседей / h</span>${data.protocol.bandwidths.map(h=>`<strong>${f(h,1)}</strong>`).join('')}${data.protocol.neighbors.map(k=>`<strong>${k}</strong>${data.protocol.bandwidths.map(h=>{const r=rows.find(r=>r.neighbors===k && r.bandwidth===h);const intensity=max-min<1e-10?.4:(r[key]-min)/(max-min);return `<button type="button" data-k="${k}" data-h="${h}" style="background:rgba(21,157,135,${.08+intensity*.38})" aria-label="${k} соседей, h ${h}, значение ${f(r[key])}">${f(r[key],key==='ch'?1:3)}</button>`;}).join('')}`).join('')}`;
      root.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>detail(rows.find(r=>r.neighbors===Number(button.dataset.k)&&r.bandwidth===Number(button.dataset.h)))));
      detail(rows.find(r=>r.neighbors===(chosen?.neighbors??8)&&r.bandwidth===(chosen?.bandwidth??1))||rows[0]);
    }
    distance.addEventListener('change',grid); metric.addEventListener('change',grid); grid();
    const best = data.networks.reduce((a,b)=>a.silhouette>b.silhouette?a:b);
    const count = data.networks.filter(r=>r.silhouette>data.baseline.silhouette).length;
    document.querySelector('#research-network-finding').textContent = `По Silhouette основную модель превосходят ${count} из ${data.networks.length} настроек. Лучший результат экономической сети ${f(best.silhouette)}: ${best.distance==='cosine'?'косинусное':'евклидово'} расстояние, ${best.neighbors} соседей, h = ${f(best.bandwidth,1)}. Перебор расширяет проверку, но не доказывает преимущество на новых данных. По другим метрикам порядок может отличаться.`;
  }).catch(error=>{document.querySelector('.sensitivity-status').textContent=`Не удалось загрузить новые проверки: ${error.message}.`;});
})();
