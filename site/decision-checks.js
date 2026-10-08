(() => {
  const synthetic = document.querySelector('#transition-check');
  if (!synthetic) return;
  const format = (value, digits = 3) => Number(value).toLocaleString('ru-RU', {minimumFractionDigits:digits,maximumFractionDigits:digits});
  fetch('decision-data.json').then(response => { if (!response.ok) throw new Error('Результаты недоступны'); return response.json(); }).then(data => {
    const choice = document.querySelector('#k-check-choice');
    choice.innerHTML = data.cluster_counts.map(row => `<option value="${row.k}" ${row.k===3?'selected':''}>K = ${row.k}</option>`).join('');
    function counts() {
      const selected = Number(choice.value);
      const rows = data.cluster_counts;
      const lower = Math.max(0,Math.floor((Math.min(...rows.map(row=>row.subsample_ari_min))-.03)*10)/10);
      const x = value => 145+(value-lower)/(1-lower)*660;
      document.querySelector('#k-check-chart').innerHTML = `<svg viewBox="0 0 920 325" role="img" aria-label="Устойчивость от двух до восьми типов на одинаковых подвыборках"><text x="145" y="22">ARI: медиана и диапазон повторений, выше лучше</text>${rows.map((row,i)=>`<text x="15" y="${57+i*32}">K = ${row.k}</text><line x1="${x(row.subsample_ari_min)}" x2="${x(row.subsample_ari_max)}" y1="${51+i*32}" y2="${51+i*32}" stroke="${row.k===selected?'#159d87':'#a9b8d0'}" stroke-width="4"/><circle cx="${x(row.subsample_ari_median)}" cy="${51+i*32}" r="6" fill="${row.k===selected?'#159d87':'#647378'}"><title>K=${row.k}: ${format(row.subsample_ari_median)}</title></circle><text x="835" y="${57+i*32}">${format(row.subsample_ari_median)}</text>`).join('')}<line x1="145" x2="805" y1="285" y2="285" stroke="#bac5d4"/>${[lower,(lower+1)/2,1].map(v=>`<text x="${x(v)}" y="315" text-anchor="middle">${format(v,2)}</text>`).join('')}</svg>`;
      const row = rows.find(row=>row.k===selected);
      document.querySelector('#k-check-readout').textContent = `K = ${selected}: Silhouette ${format(row.silhouette)}, ARI соседних месяцев ${format(row.temporal_ari)}. Медиана минимального Жаккара ${format(row.min_jaccard_median)}; самая маленькая группа содержит ${format(100*row.min_monthly_share,1)}% территорий в своём месяце.`;
    }
    choice.addEventListener('change',counts); counts();
    const scenario = document.querySelector('#synthetic-scenario');
    scenario.innerHTML = data.protocol.scenarios.map(row=>`<option value="${row.id}" ${row.id==='calibrated'?'selected':''}>${row.name}</option>`).join('');
    const filter = document.querySelector('#synthetic-persistent');
    function transitions() {
      const rows = data.synthetic.filter(row=>row.scenario===scenario.value && row.rule===(filter.checked?'persistent':'all'));
      const metrics = [['precision','Найденные смены верны'],['recall','Настоящие смены найдены'],['false_stable_percent','Ложный сигнал у стабильных']];
      const x = value => 360+value*440;
      document.querySelector('#synthetic-chart').innerHTML = `<svg viewBox="0 0 920 230" role="img" aria-label="Проверка найденных переходов на синтетических данных">${metrics.map(([key,label],i)=>`<text x="0" y="${52+i*57}">${label}</text><line x1="360" x2="800" y1="${46+i*57}" y2="${46+i*57}" stroke="#d9dde3"/>${rows.map(row=>{const value=key==='false_stable_percent'?row[key]/100:row[key]; const offset=row.model==='dynamic'?7:-7; return value===null ? `<text x="360" y="${50+i*57+offset}" font-size="12">${key==='recall'?'Нет настоящих смен':'Не найдено событий'}</text>` : `<circle cx="${x(value)}" cy="${46+i*57+offset}" r="6" fill="${row.model==='dynamic'?'#159d87':'#8291a8'}"><title>${row.model==='dynamic'?'Динамическая сеть':'Только признаки'}: ${format(value*100,1)}%</title></circle>`;}).join('')}`).join('')}${[0,.5,1].map(v=>`<text x="${x(v)}" y="220" text-anchor="middle">${v*100}%</text>`).join('')}</svg>`;
      const row = rows.find(row=>row.model==='dynamic');
      const precision = row.precision===null?'нет оценки':`${format(100*row.precision,1)}%`;
      const recall = row.recall===null?'В сценарии нет настоящих смен.':`Найдено ${format(100*row.recall,1)}% настоящих смен.`;
      document.querySelector('#synthetic-readout').textContent = `Динамическая сеть: верны ${precision} найденных событий. ${recall} Ложный сигнал получили ${format(row.false_stable_percent,1)}% стабильных узлов. Итог по ${data.protocol.synthetic_runs} генерациям: ${row.matched_events} совпадений, ${row.false_events} ложных событий.`;
    }
    scenario.addEventListener('change',transitions); filter.addEventListener('change',transitions); transitions();
    const raw = data.synthetic.find(row=>row.scenario==='calibrated' && row.model==='dynamic' && row.rule==='all');
    const filtered = data.synthetic.find(row=>row.scenario==='calibrated' && row.model==='dynamic' && row.rule==='persistent');
    document.querySelector('#synthetic-finding').textContent = `При масштабе реальных остатков фильтр снижает ложные сигналы у стабильных узлов с ${format(raw.false_stable_percent,1)}% до ${format(filtered.false_stable_percent,1)}%, но находит ${format(filtered.recall*100,1)}% настоящих смен. Это полезный фильтр с заметными пропусками, а не гарантия достоверности.`;
  }).catch(error=>document.querySelectorAll('.decision-status').forEach(node=>node.textContent=`Не удалось загрузить проверку: ${error.message}.`));
})();
