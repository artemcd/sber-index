(() => {
  const root = document.querySelector('#research');
  if (!root) return;
  const format = (value, digits = 3) => Number(value).toLocaleString('ru-RU', {maximumFractionDigits: digits, minimumFractionDigits: digits});
  const colors = ['#159d87', '#ba710f', '#8063ce'];
  fetch('research-data.json').then(response => { if (!response.ok) throw new Error('Данные недоступны'); return response.json(); }).then(data => {
    document.querySelector('#research-robust-value').textContent = format(data.robustness.median);
    document.querySelector('#research-robust-range').textContent = `От ${format(data.robustness.min)} до ${format(data.robustness.max)} в ${data.protocol.subsamples} повторениях. В каждом заново строим сеть и обучаем модель на случайных 80% территорий.`;
    const low = Math.max(0, Math.floor((data.robustness.min - .02) * 20) / 20);
    const x = value => 60 + (value-low)/(1-low)*800;
    document.querySelector('#research-robust-chart').innerHTML = `<svg viewBox="0 0 920 190" role="img" aria-label="Сходство с исходными типами в двадцати повторениях"><line x1="60" y1="130" x2="860" y2="130" stroke="#bac5d4"/>${[low,(low+1)/2,1].map(v => `<text x="${x(v)}" y="162" text-anchor="middle">${format(v,2)}</text>`).join('')}${data.robustness.runs.map((v,i) => `<circle tabindex="0" cx="${x(v)}" cy="${58+(i%4)*17}" r="6" fill="#159d87"><title>Повтор ${i+1}: ARI ${format(v)}</title></circle>`).join('')}<text x="60" y="22">Каждая точка: средний ARI за 24 месяца</text></svg>`;
    const income = data.external.find(row => row.metric === 'income' && row.year === 2024);
    const housing = data.external.find(row => row.metric === 'housing' && row.year === 2024);
    document.querySelector('#research-final-finding').textContent = `Главный вывод: группы устойчивы к удалению части территорий (ARI ${format(data.robustness.median)}) и несут информацию сверх региона и размера. В проверке за 2024 год тип снижает ошибку описания доходов на ${format(income.mse_reduction_percent,1)}%, жилья на ${format(housing.mse_reduction_percent,1)}%. Связь с инвестициями слабее. Это типология потребления и окружения, а не рейтинг благополучия.`;
    const metricSelect = document.querySelector('#research-external-metric');
    const yearSelect = document.querySelector('#research-external-year');
    function external() {
      const row = data.external.find(row => row.metric===metricSelect.value && row.year===Number(yearSelect.value));
      document.querySelector('#research-external-value').textContent = `${format(row.mse_reduction_percent,1)}%`;
      document.querySelector('#research-external-explanation').textContent = row.mse_reduction_percent>0 ? 'Снижение ошибки при добавлении типа муниципалитета' : 'Тип не уменьшил ошибку по сравнению с регионом и населением';
      document.querySelector('#research-external-count').textContent = `${row.n.toLocaleString('ru-RU')} территорий с данными за оба года. Тип взят на декабрь выбранного года.`;
      const units = {income:'тыс. ₽ на жителя',housing:'м² на жителя',investment:'тыс. ₽ на жителя'};
      document.querySelector('#research-external-profiles').innerHTML = row.profiles.map(profile => `<div style="--profile-color:${colors[profile.cluster-1]}"><span>${data.clusters.find(c=>c.id===profile.cluster).name}</span><strong>${format(profile.median,metricSelect.value==='housing'?2:0)}</strong><small>${units[metricSelect.value]}<br>Медиана, ${profile.n} территорий</small></div>`).join('');
      const entries = data.external.filter(item => item.year===row.year);
      const bound = Math.max(2,...entries.map(item => Math.abs(item.mse_reduction_percent)))*1.2;
      const position = value => 575+value/bound*245;
      document.querySelector('#research-external-chart').innerHTML = `<svg viewBox="0 0 920 218" role="img" aria-label="Снижение ошибки на отложенных территориях при добавлении типа"><line x1="575" y1="30" x2="575" y2="176" stroke="#8291a8"/>${entries.map((item,i)=>`<text x="0" y="${66+i*46}">${{income:'Доходы и выплаты',housing:'Ввод жилья',investment:'Инвестиции'}[item.metric]}</text><line x1="575" y1="${60+i*46}" x2="${position(item.mse_reduction_percent)}" y2="${60+i*46}" stroke="#159d87" stroke-width="3"/><circle cx="${position(item.mse_reduction_percent)}" cy="${60+i*46}" r="6" fill="${item.metric===metricSelect.value?'#159d87':'#8291a8'}"/><text x="${position(item.mse_reduction_percent)+12}" y="${66+i*46}">${format(item.mse_reduction_percent,1)}%</text>`).join('')}<text x="575" y="205" text-anchor="middle">0: тип ничего не добавляет</text></svg>`;
    }
    metricSelect.addEventListener('change',external); yearSelect.addEventListener('change',external); external();
  }).catch(error => { root.querySelector('.research-status').textContent = `Не удалось загрузить результаты: ${error.message}. Обновите страницу через локальный сервер.`; });
})();
