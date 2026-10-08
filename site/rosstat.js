function rosstatPanel(items, context, metric) {
  const byId = new Map(context.municipalities.map(row => [row.id, row]));
  return items.flatMap(item => {
    const values = byId.get(item.id)?.[metric];
    if (!values || !values.every(value => Number.isFinite(value) && value >= 0)) return [];
    const spending = [0, 12].map(start => item.history.spend.slice(start, start + 12).reduce((a, b) => a + b, 0) / 12);
    return [{...item, values, spending}];
  });
}

async function createRosstatContext(data, palette, openMunicipality) {
  const response = await fetch("rosstat-data.json?v=1");
  if (!response.ok) throw new Error("Не удалось загрузить контекст Росстата");
  const context = await response.json();
  const format = (value, digits = 0) => new Intl.NumberFormat("ru-RU", {maximumFractionDigits: digits}).format(value);
  const node = (tag, attrs = {}, text) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const units = {income: "тыс. ₽/жителя за год", housing: "м²/жителя за год", investment: "тыс. ₽/жителя за год"};
  const titles = {income: "Доходы и потребление", housing: "Ввод жилья по типам", investment: "Инвестиции: 2023 → 2024"};
  let selectedId = null;
  const panels = Object.fromEntries(Object.keys(units).map(metric => {
    const element = document.querySelector(`[data-panel="${metric}"]`);
    return [metric, {element, rows: rosstatPanel(data.municipalities, context, metric), highlight: 0,
                    chart: element.querySelector("svg"), readout: element.querySelector(".context-readout")}];
  }));
  const labels = new Map(data.municipalities.map(item => [`${item.name}, ${item.region}`, item.id]));
  document.querySelector("#context-places").replaceChildren(...[...labels.keys()].sort((a, b) => a.localeCompare(b, "ru")).map(label => {
    const option = document.createElement("option"); option.value = label; return option;
  }));

  function choose(id) {
    selectedId = id;
    const item = data.municipalities.find(row => row.id === id);
    Object.values(panels).forEach(panel => { panel.element.querySelector("input").value = item ? `${item.name}, ${item.region}` : ""; });
    drawAll();
  }
  function point(panel, item, x, y, label, radius = 3) {
    const selected = item.id === selectedId;
    const circle = node("circle", {cx: x, cy: y, r: selected ? 6 : radius, fill: palette[item.cluster],
      class: `context-dot${selected ? " is-selected" : ""}`, "data-id": item.id,
      opacity: selected || !panel.highlight || panel.highlight === item.cluster ? .75 : .08});
    circle.append(node("title", {}, label));
    circle.addEventListener("pointerenter", () => { panel.readout.textContent = label; });
    circle.addEventListener("click", () => choose(item.id));
    panel.chart.append(circle);
    return circle;
  }
  function axis(chart, values, left, right, bottom, logarithmic = false) {
    const maximum = Math.max(...values, 1);
    const log = logarithmic && values.every(value => value > 0);
    const low = log ? 10 ** Math.floor(Math.log10(Math.min(...values))) : 0;
    const high = log ? 10 ** Math.ceil(Math.log10(maximum)) : Math.ceil(maximum);
    const transform = log ? Math.log10 : value => value;
    const x = value => left + (transform(value) - transform(low)) / (transform(high) - transform(low) || 1) * (right - left);
    const ticks = log ? Array.from({length: Math.round(Math.log10(high / low)) + 1}, (_, i) => low * 10 ** i)
      : Array.from({length: 5}, (_, i) => high * i / 4);
    ticks.forEach(value => chart.append(node("line", {x1: x(value), x2: x(value), y1: 42, y2: bottom, class: "chart-grid"}),
      node("text", {x: x(value), y: bottom + 23, "text-anchor": "middle", class: "chart-label"}, format(value, value < 1 ? 2 : 1))));
    return {x, log};
  }
  function draw(metric) {
    const panel = panels[metric], chart = panel.chart;
    const year = Number(panel.element.querySelector(".context-year")?.value ?? 2024) - 2023;
    const region = panel.element.querySelector(".context-region")?.value ?? "";
    const rows = panel.rows.filter(item => !region || item.region === region);
    chart.replaceChildren();
    panel.element.querySelector("figcaption").textContent = `${titles[metric]}${metric === "investment" ? "" : `, ${2023 + year}`}`;
    panel.element.querySelector(".context-coverage").textContent = `${format(rows.length)} из ${format(data.municipalities.filter(item => !region || item.region === region).length)} территорий, одна панель за оба года`;
    panel.element.querySelector(".context-open").disabled = selectedId === null;
    const selected = rows.find(item => item.id === selectedId);
    const chosen = data.municipalities.find(item => item.id === selectedId);
    panel.readout.textContent = chosen && !selected ? `${chosen.name}: нет сопоставимых данных за оба года или территория вне выбранного региона.` : "Наведите на точку или найдите муниципалитет по названию.";
    const legend = panel.element.querySelector(".context-legend");
    legend.replaceChildren(...data.clusters.map(type => {
      const button = document.createElement("button"); button.type = "button";
      button.setAttribute("aria-pressed", String(panel.highlight === type.id));
      const mark = document.createElement("i"); mark.style.background = palette[type.id];
      button.append(mark, document.createTextNode(`${type.name}, ${format(rows.filter(item => item.cluster === type.id).length)}`));
      button.addEventListener("click", () => { panel.highlight = panel.highlight === type.id ? 0 : type.id; draw(metric); });
      return button;
    }));
    if (!rows.length) {
      chart.append(node("text", {x: 400, y: 180, "text-anchor": "middle", class: "context-label"}, "Нет сопоставимых данных за оба года"));
      return;
    }
    if (metric === "income") {
      const {x, log} = axis(chart, rows.flatMap(item => item.values), 68, 760, 310, true);
      const high = Math.ceil(Math.max(...rows.flatMap(item => item.spending)) / 20000) * 20000;
      const y = value => 310 - value / high * 262;
      for (let value = 0; value <= high; value += high / 4) chart.append(node("line", {x1: 68, x2: 760, y1: y(value), y2: y(value), class: "chart-grid"}),
        node("text", {x: 58, y: y(value) + 5, "text-anchor": "end", class: "chart-label"}, format(value / 1000)));
      chart.append(node("text", {x: 68, y: 22, class: "context-label"}, "Безналичные расходы, тыс. ₽ в месяц"),
        node("text", {x: 760, y: 365, "text-anchor": "end", class: "context-label"}, `Доходы и выплаты, тыс. ₽/жителя${log ? ", лог. шкала" : ""}`));
      rows.forEach(item => point(panel, item, x(item.values[year]), y(item.spending[year]),
        `${item.name}, ${item.region}, ${2023 + year}: доходы и выплаты ${format(item.values[year], 1)} тыс. ₽/жителя за год; расходы ${format(item.spending[year])} ₽/месяц.`));
      if (selected) panel.readout.textContent = `${selected.name}, ${2023 + year}: ${format(selected.values[year], 1)} тыс. ₽/жителя за год; расходы ${format(selected.spending[year])} ₽/месяц.`;
    } else if (metric === "housing") {
      const {x} = axis(chart, rows.flatMap(item => item.values), 70, 760, 310);
      const spacing = 240 / data.clusters.length;
      data.clusters.forEach((type, index) => {
        const group = rows.filter(item => item.cluster === type.id), y = 76 + index * spacing;
        chart.append(node("text", {x: 28, y: y + 5, class: "context-label", fill: palette[type.id]}, `0${type.id}`));
        if (!group.length) return;
        const values = group.map(item => item.values[year]);
        const middle = median(values);
        chart.append(node("line", {x1: x(percentile(values, .25)), x2: x(percentile(values, .75)), y1: y, y2: y,
          stroke: palette[type.id], "stroke-width": 20, opacity: .12}));
        group.forEach(item => point(panel, item, x(item.values[year]), y + ((item.id * 37 % 29) - 14),
          `${item.name}, ${item.region}, ${2023 + year}: ${format(item.values[year], 3)} м²/жителя; ${type.name}.`, 2.5));
        chart.append(node("line", {x1: x(middle), x2: x(middle), y1: y - 18, y2: y + 18, stroke: "#fff", "stroke-width": 2}),
          node("text", {x: x(middle) + 8, y: y - 24, class: "context-label"}, `медиана ${format(middle, 2)}`));
      });
      chart.append(node("text", {x: 760, y: 365, "text-anchor": "end", class: "context-label"}, "Введено жилья, м² на жителя за год"));
      if (selected) panel.readout.textContent = `${selected.name}, ${2023 + year}: ${format(selected.values[year], 3)} м²/жителя за год.`;
    } else {
      const order = panel.element.querySelector(".context-order").value;
      const score = item => order === "growth" ? item.values[1] - item.values[0] : item.values[1];
      const shown = [...rows].sort((a, b) => score(b) - score(a) || a.id - b.id).slice(0, 7);
      if (selected && !shown.includes(selected)) shown.push(selected);
      const {x, log} = axis(chart, shown.flatMap(item => item.values), 215, 738, 318, true);
      chart.append(node("text", {x: 738, y: 22, "text-anchor": "end", class: "context-label"}, "○ 2023    ● 2024"));
      shown.forEach((item, index) => {
        const y = 57 + index * 34;
        const name = item.name.length > 20 ? `${item.name.slice(0, 19)}…` : item.name;
        const label = node("text", {x: 200, y: y + 5, "text-anchor": "end", class: "context-label"}, name);
        label.append(node("title", {}, `${item.name}, ${item.region}`)); chart.append(label);
        chart.append(node("line", {x1: x(item.values[0]), x2: x(item.values[1]), y1: y, y2: y, stroke: palette[item.cluster],
          "stroke-width": 2, opacity: !panel.highlight || panel.highlight === item.cluster ? .7 : .08}));
        const detail = `${item.name}, ${item.region}: ${format(item.values[0], 1)} → ${format(item.values[1], 1)} тыс. ₽/жителя; изменение ${format(item.values[1] - item.values[0], 1)} тыс. ₽.`;
        const before = point(panel, item, x(item.values[0]), y, detail, 5);
        before.setAttribute("fill", "#080f1c"); before.setAttribute("stroke", palette[item.cluster]); before.setAttribute("stroke-width", "2");
        point(panel, item, x(item.values[1]), y, detail, 5);
        if (item.id === selectedId) panel.readout.textContent = detail;
      });
      chart.append(node("text", {x: 738, y: 365, "text-anchor": "end", class: "context-label"}, `тыс. ₽/жителя за год${log ? ", лог. шкала" : ""}`));
      panel.element.querySelector(".context-selection").textContent = `Показаны ${Math.min(7, rows.length)} лидеров ${order === "growth" ? "по приросту на жителя" : "по уровню 2024 года"}${selected && !shown.slice(0, 7).includes(selected) ? " и выбранная территория" : ""}.`;
    }
    chart.querySelectorAll(".context-dot.is-selected").forEach(circle => chart.append(circle));
  }
  function drawAll() { Object.keys(panels).forEach(draw); }
  Object.entries(panels).forEach(([metric, panel]) => {
    const regionSelect = panel.element.querySelector(".context-region");
    if (regionSelect) {
      [...new Set(data.municipalities.map(item => item.region))].sort((a, b) => a.localeCompare(b, "ru")).forEach(region => {
        const option = document.createElement("option"); option.value = region; option.textContent = region; regionSelect.append(option);
      });
    }
    panel.element.querySelectorAll("select").forEach(select => select.addEventListener("change", () => draw(metric)));
    panel.element.querySelector("form").addEventListener("submit", event => {
      event.preventDefault();
      const input = panel.element.querySelector("input");
      const id = labels.get(input.value.trim());
      if (input.value.trim() && id === undefined) { input.setCustomValidity("Выберите муниципалитет из списка"); input.reportValidity(); return; }
      choose(id ?? null);
    });
    panel.element.querySelector("input").addEventListener("input", event => event.target.setCustomValidity(""));
    panel.element.querySelector(".context-open").addEventListener("click", () => { if (selectedId !== null) openMunicipality(selectedId); });
  });
  drawAll();
}

if (typeof module !== "undefined") module.exports = {rosstatPanel};
