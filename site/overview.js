function summarizeTrajectories(items, types, months) {
  return Array.from({length: months}, (_, month) => {
    const counts = Array(types + 1).fill(0);
    const matrix = Array.from({length: types + 1}, () => Array(types + 1).fill(0));
    const changed = [];
    items.forEach(item => {
      const type = item.trajectory[month];
      counts[type]++;
      if (month) {
        const before = item.trajectory[month - 1];
        matrix[before][type]++;
        if (before !== type) changed.push(item.id);
      }
    });
    return {counts, matrix, changed};
  });
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function cohortSeries(items, types, months, metric) {
  return Array.from({length: types}, (_, index) => {
    const group = items.filter(item => item.trajectory[months - 1] === index + 1);
    return {id: index + 1, count: group.length, values: Array.from({length: months}, (_, month) => median(group.map(item => item.history[metric][month])))};
  });
}

function histogram(values, step = 5000, maximum = Math.max(...values)) {
  const bins = Array.from({length: Math.floor(maximum / step) + 1}, (_, i) => ({low: i * step, high: (i + 1) * step, count: 0}));
  values.forEach(value => bins[Math.floor(value / step)].count++);
  return bins;
}

function percentile(values, fraction) {
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * fraction;
  return sorted[Math.floor(index)] + (sorted[Math.ceil(index)] - sorted[Math.floor(index)]) * (index % 1);
}

function endpointFlows(items, types, different = false) {
  const flows = Array.from({length: types * types}, (_, i) => ({from: Math.floor(i / types) + 1, to: i % types + 1, ids: []}));
  items.forEach(item => {
    const from = item.trajectory[0], to = item.trajectory.at(-1);
    if (!different || from !== to) flows[(from - 1) * types + to - 1].ids.push(item.id);
  });
  return flows.filter(flow => flow.ids.length);
}

function createExplorer(data, palette, openMunicipality) {
  const items = data.municipalities;
  const stats = summarizeTrajectories(items, data.clusters.length, data.meta.months);
  const monthName = month => new Intl.DateTimeFormat("ru-RU", {month: "long", year: "numeric", timeZone: "UTC"}).format(new Date(Date.UTC(2023, month, 1)));
  const number = (value, digits = 0) => new Intl.NumberFormat("ru-RU", {maximumFractionDigits: digits}).format(value);
  const node = (tag, attributes = {}, text) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const activate = (element, label, action) => {
    element.setAttribute("role", "button");
    element.setAttribute("tabindex", "0");
    element.setAttribute("aria-label", label);
    element.addEventListener("click", action);
    element.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); action(); }
    });
  };
  let month = 23;
  let typeFilter = 0;
  let pair = null;
  let selected;
  let timer;
  let zoom = [0, 0, 1000, 440];
  const map = document.querySelector("#map");
  const points = new Map([...(map?.querySelectorAll(".municipality") || [])].map(point => [Number(point.dataset.id), point]));
  const changedOnly = document.querySelector("#changed-only") || {checked: false};
  const layer = document.querySelector("#map-layer") || {value: "type"};
  const visible = item => (!typeFilter || item.trajectory[month] === typeFilter)
    && (!changedOnly.checked || (month > 0 && item.trajectory[month] !== item.trajectory[month - 1]))
    && (!pair || (month > 0 && item.trajectory[month - 1] === pair[0] && item.trajectory[month] === pair[1]));

  const byId = new Map(items.map(item => [item.id, item]));
  const peers = (target, candidates, index) => {
    target.replaceChildren(...candidates.slice(0, 3).map(item => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = `${item.name} · ${item.region}`;
      button.addEventListener("click", () => { setMonth(index); openMunicipality(item.id); });
      return button;
    }));
  };

  let networkMonth = 23, networkLayer = "transport";
  const place = document.querySelector("#network-place");
  data.exploration.networks.forEach(network => {
    const option = document.createElement("option"); option.value = network.center; option.textContent = byId.get(network.center).name; place.append(option);
  });
  function drawNetwork() {
    const network = data.exploration.networks.find(row => row.center === Number(place.value));
    const chart = document.querySelector("#network-chart"); chart.replaceChildren();
    const center = byId.get(network.center);
    const maximum = Math.max(...network.edges.flatMap(edge => edge.weights), ...network.edges.map(edge => edge.transport));
    document.querySelector("#network-month-label").textContent = monthName(networkMonth);
    const readout = document.querySelector("#network-readout");
    readout.textContent = `${center.name} · ${network.edges.length} прямых соседей · ${networkLayer === "transport" ? "транспортный вес постоянен" : "вес зависит от сходства трат"}`;
    network.edges.forEach((edge, index) => {
      const angle = index / network.edges.length * Math.PI * 2 - Math.PI / 2;
      const cx = 400 + Math.cos(angle) * 290, cy = 186 + Math.sin(angle) * 155;
      const weight = networkLayer === "transport" ? edge.transport : edge.weights[networkMonth];
      const line = node("line", {x1: 400, y1: 186, x2: cx, y2: cy, stroke: networkLayer === "transport" ? "#456080" : "#41dfc4", "stroke-width": 1 + weight / maximum * 10, opacity: .25 + weight / maximum * .65});
      const neighbor = byId.get(edge.id);
      const label = `${center.name} → ${neighbor.name}: вес ${number(weight, 4)}`;
      activate(line, label, () => { readout.textContent = label; });
      line.append(node("title", {}, label)); line.addEventListener("pointerenter", () => { readout.textContent = label; }); chart.append(line);
      const point = node("circle", {cx, cy, r: 7, class: "network-node"});
      const show = () => { readout.textContent = `${neighbor.name} · ${neighbor.region} · ${number(neighbor.history.spend[networkMonth])} ₽/месяц · маркетплейсы ${number(neighbor.history.marketplace_share[networkMonth], 2)}%`; };
      activate(point, `${neighbor.name}, показать показатели`, show); point.addEventListener("pointerenter", show); point.addEventListener("focus", show); chart.append(point);
    });
    chart.append(node("circle", {cx: 400, cy: 186, r: 17, class: "network-center"}), node("text", {x: 400, y: 220, "text-anchor": "middle", class: "network-name"}, center.name));
  }
  place.addEventListener("change", drawNetwork);
  document.querySelector("#network-month").addEventListener("input", event => { networkMonth = Number(event.target.value); drawNetwork(); });
  document.querySelector("#network-layer").addEventListener("click", event => {
    const button = event.target.closest("[data-layer]"); if (!button) return;
    networkLayer = button.dataset.layer;
    document.querySelectorAll("#network-layer button").forEach(item => item.setAttribute("aria-pressed", item === button)); drawNetwork();
  });

  let coverageFilter = "all";
  function drawCoverage() {
    const chart = document.querySelector("#coverage-chart"); chart.replaceChildren();
    const coverage = data.exploration.coverage;
    const counts = new Map(); coverage.forEach(([, months]) => counts.set(months, (counts.get(months) || 0) + 1));
    const missing = coverage.filter(([id, months]) => months === 24 && !byId.has(id)).length;
    const readout = document.querySelector("#coverage-readout");
    readout.textContent = `${number(items.length)} из ${number(coverage.length)} территорий в модели · ${number(items.length / coverage.length * 100, 1)}% исходного охвата`;
    const groups = [["#41dfc4", "В модели", items.length], ["#ffb454", "Неполный ряд", coverage.filter(row => row[1] < 24).length]];
    if (missing) groups.push(["#7890b0", "Без сопоставления Росстата", missing]);
    const legend = document.querySelector("#coverage-legend");
    legend.replaceChildren(...groups.map(([color, label, count]) => {
      const span = document.createElement("span"), mark = document.createElement("i"); mark.style.background = color; span.append(mark, document.createTextNode(`${label} · ${number(count)}`)); return span;
    }));
    coverage.forEach(([id, months], index) => {
      const included = byId.has(id);
      const point = node("circle", {cx: 35 + index % 73 * 10, cy: 25 + Math.floor(index / 73) * 10, r: 3.1, fill: included ? "#41dfc4" : months < 24 ? "#ffb454" : "#7890b0", opacity: coverageFilter === "all" || (coverageFilter === "included" ? included : !included) ? 1 : .09});
      const count = counts.get(months);
      const label = `${months} из 24 месяцев · ${number(count)} территорий с такой полнотой · ${included ? "в модели" : months < 24 ? "исключён неполный ряд" : "не сопоставлен с Росстатом"}`;
      point.append(node("title", {}, label)); point.addEventListener("pointerenter", () => { readout.textContent = label; }); chart.append(point);
    });
  }
  document.querySelector("#coverage-filter").addEventListener("click", event => {
    const button = event.target.closest("[data-filter]"); if (!button) return; coverageFilter = button.dataset.filter;
    document.querySelectorAll("#coverage-filter button").forEach(item => item.setAttribute("aria-pressed", item === button)); drawCoverage();
  });

  let distributionMonth = 23;
  const spendingMaximum = Math.max(...items.map(item => Math.max(...item.history.spend)));
  function drawDistribution() {
    const values = items.map(item => item.history.spend[distributionMonth]);
    const bins = histogram(values, 5000, spendingMaximum);
    const chart = document.querySelector("#distribution-chart"); chart.replaceChildren();
    const height = Math.max(...bins.map(bin => bin.count));
    const maximum = bins.at(-1).high;
    const x = value => 55 + value / maximum * 710, y = count => 285 - count / height * 230;
    for (const count of [0, Math.round(height / 2), height]) chart.append(node("line", {x1: 55, x2: 765, y1: y(count), y2: y(count), class: "chart-grid"}), node("text", {x: 45, y: y(count) + 4, "text-anchor": "end", class: "chart-label"}, number(count)));
    for (let value = 0; value <= maximum; value += 20000) chart.append(node("text", {x: x(value), y: 311, "text-anchor": "middle", class: "chart-label"}, `${number(value / 1000)} тыс.`));
    chart.append(node("text", {x: 55, y: 26, class: "studio-axis-title"}, "Муниципалитеты"), node("text", {x: 765, y: 342, "text-anchor": "end", class: "studio-axis-title"}, "Расходы, ₽ в месяц"));
    const middle = median(values);
    const readout = document.querySelector("#distribution-readout");
    readout.textContent = `Медиана: ${number(middle)} ₽ · центральные 80% территорий: ${number(percentile(values, .1))}–${number(percentile(values, .9))} ₽`;
    const examples = document.querySelector("#distribution-peers"); examples.replaceChildren();
    bins.forEach(bin => {
      const group = node("g", {class: "distribution-bin", "data-low": bin.low});
      group.append(node("rect", {x: x(bin.low) + 1, y: y(bin.count), width: 710 / bins.length - 2, height: 285 - y(bin.count), fill: "#41dfc4"}));
      const label = `${number(bin.low)}–${number(bin.high)} ₽: ${number(bin.count)} территорий; верхняя граница не включена`;
      group.append(node("title", {}, label));
      activate(group, label, () => {
        readout.textContent = `${number(bin.low)}–${number(bin.high)} ₽ · ${number(bin.count)} территорий`;
        chart.querySelectorAll(".distribution-bin").forEach(mark => mark.classList.toggle("is-selected", mark === group));
        peers(examples, items.filter(item => item.history.spend[distributionMonth] >= bin.low && item.history.spend[distributionMonth] < bin.high), distributionMonth);
      }); chart.append(group);
    });
    chart.append(node("line", {x1: x(middle), x2: x(middle), y1: 43, y2: 285, class: "studio-reference"}), node("text", {x: x(middle) + 7, y: 45, class: "studio-axis-title"}, "медиана"));
    document.querySelector("#distribution-month-label").textContent = monthName(distributionMonth);
  }
  document.querySelector("#distribution-month").addEventListener("input", event => { distributionMonth = Number(event.target.value); drawDistribution(); });

  function drawCalendar() {
    const chart = document.querySelector("#calendar-chart"); chart.replaceChildren();
    const names = {marketplace_share: "Маркетплейсы", grocery_share: "Продукты", food_service_share: "Общепит", health_share: "Здоровье", transport_share: "Транспорт"};
    const maximum = Math.max(...Object.keys(names).flatMap(key => data.historyMedian[key].map(value => Math.abs(value - data.historyMedian[key][0])))) || 1;
    const color = value => value >= 0 ? `hsl(170 66% ${16 + value / maximum * 40}%)` : `hsl(35 85% ${15 - value / maximum * 50}%)`;
    const readout = document.querySelector("#calendar-readout");
    readout.textContent = "Выберите категорию и месяц на календаре.";
    Object.entries(names).forEach(([key, name], row) => {
      chart.append(node("text", {x: 150, y: 69 + row * 45, "text-anchor": "end", class: "chart-label"}, name));
      data.historyMedian[key].forEach((value, index) => {
        const delta = value - data.historyMedian[key][0];
        const rect = node("rect", {x: 166 + index * 25, y: 48 + row * 45, width: 22, height: 34, rx: 2, fill: color(delta), class: "calendar-cell"});
        const label = `${name} · ${monthName(index)}: ${number(value, 2)}% · ${delta > 0 ? "+" : ""}${number(delta, 2)} п.п. к январю 2023`;
        const show = () => { readout.textContent = label; };
        activate(rect, label, () => { chart.querySelectorAll(".calendar-cell").forEach(cell => cell.classList.toggle("is-selected", cell === rect)); show(); });
        rect.append(node("title", {}, label)); rect.addEventListener("pointerenter", show); rect.addEventListener("focus", show); chart.append(rect);
      });
    });
    for (const [index, label] of [[0, "янв 2023"], [12, "янв 2024"], [23, "дек 2024"]]) chart.append(node("text", {x: 166 + index * 25, y: 28, "text-anchor": index === 23 ? "end" : "start", class: "chart-label"}, label));
    for (let i = 0; i <= 20; i++) chart.append(node("rect", {x: 216 + i * 22, y: 304, width: 22, height: 10, fill: color((i - 10) / 10 * maximum)}));
    for (const [x, value] of [[216, -maximum], [447, 0], [678, maximum]]) chart.append(node("text", {x, y: 340, "text-anchor": "middle", class: "chart-label"}, `${value > 0 ? "+" : ""}${number(value, 1)} п.п.`));
  }

  function drawFlows() {
    const different = document.querySelector("#flows-different").checked;
    const flows = endpointFlows(items, data.clusters.length, different);
    const total = flows.reduce((sum, flow) => sum + flow.ids.length, 0);
    const chart = document.querySelector("#flows-chart"); chart.replaceChildren();
    const readout = document.querySelector("#flows-readout"), examples = document.querySelector("#flows-peers"); examples.replaceChildren();
    readout.textContent = `${number(total)} территорий · ${different ? "разные типы на старте и финише" : "вся панель"}`;
    if (!total) return;
    const scale = (295 - (data.clusters.length - 1) * 14) / total;
    const leftCursor = {}, rightCursor = {};
    const legend = document.querySelector("#flows-legend");
    legend.replaceChildren(...data.clusters.map(type => {
      const label = document.createElement("span"), mark = document.createElement("i"); mark.style.background = palette[type.id];
      label.append(mark, document.createTextNode(`0${type.id} · ${type.name}`)); return label;
    }));
    for (const [side, cursor, key] of [["left", leftCursor, "from"], ["right", rightCursor, "to"]]) {
      let top = 62;
      data.clusters.forEach(type => {
        const count = flows.filter(flow => flow[key] === type.id).reduce((sum, flow) => sum + flow.ids.length, 0);
        cursor[type.id] = top;
        chart.append(node("rect", {x: side === "left" ? 140 : 650, y: top, width: 10, height: count * scale, fill: palette[type.id]}), node("text", {x: side === "left" ? 128 : 672, y: top + count * scale / 2 + 4, "text-anchor": side === "left" ? "end" : "start", class: "studio-type-label"}, `0${type.id} · ${number(count)}`));
        top += count * scale + 14;
      });
    }
    chart.append(node("text", {x: 140, y: 27, class: "studio-axis-title"}, "Январь 2023"), node("text", {x: 660, y: 27, "text-anchor": "end", class: "studio-axis-title"}, "Декабрь 2024"));
    flows.forEach(flow => {
      const height = flow.ids.length * scale, y1 = leftCursor[flow.from], y2 = rightCursor[flow.to];
      leftCursor[flow.from] += height; rightCursor[flow.to] += height;
      const ribbon = node("path", {d: `M150,${y1} C390,${y1} 410,${y2} 650,${y2} L650,${y2 + height} C410,${y2 + height} 390,${y1 + height} 150,${y1 + height} Z`, fill: palette[flow.from], class: "flow-ribbon", "data-from": flow.from, "data-to": flow.to});
      const label = `${data.clusters[flow.from - 1].name} → ${data.clusters[flow.to - 1].name}: ${number(flow.ids.length)} территорий`;
      const show = () => { readout.textContent = label; };
      ribbon.append(node("title", {}, label)); activate(ribbon, label, () => { chart.querySelectorAll(".flow-ribbon").forEach(path => path.classList.toggle("is-selected", path === ribbon)); show(); peers(examples, flow.ids.map(id => byId.get(id)), 23); });
      ribbon.addEventListener("pointerenter", show); ribbon.addEventListener("focus", show); chart.append(ribbon);
    });
  }
  document.querySelector("#flows-different").addEventListener("change", drawFlows);

  const studio = document.querySelector("#studio-chart");
  let view = "geo";
  let metric = "marketplace_share";
  const snapshot = 23;
  const openAtlas = index => { setMonth(index); document.querySelector("#atlas").scrollIntoView({behavior: "smooth"}); };
  const categories = {marketplace_share: "маркетплейсов", grocery_share: "продуктов", food_service_share: "общепита", health_share: "здоровья", transport_share: "транспорта"};
  const cohortCache = new Map();
  const metricMax = Object.fromEntries(Object.keys(categories).map(key => [key, Math.ceil(Math.max(...items.map(item => Math.max(...item.history[key]))) / 5) * 5]));
  const indexMax = Math.ceil(Math.max(...items.map(item => Math.max(...item.history.spendIndex))) / 50) * 50;
  const studioPoints = new Map();
  const studioTooltip = document.querySelector("#studio-tooltip");
  if (studio) items.forEach(item => {
    const point = node("circle", {r: 2.6, class: "studio-point", "data-id": item.id});
    activate(point, `${item.name}, ${item.region}`, () => { setMonth(snapshot); openMunicipality(item.id); });
    const tooltip = () => {
      studioTooltip.textContent = view === "geo" ? `${item.name} · ${item.region}\n${data.clusters[item.trajectory[snapshot] - 1].name}` : `${item.name} · ${item.region}\n${monthName(snapshot)}: ${number(item.history[metric][snapshot], 2)}% · индекс расходов ${number(item.history.spendIndex[snapshot], 1)}\n${data.clusters[item.trajectory[snapshot] - 1].name}`;
      const box = document.querySelector(".studio").getBoundingClientRect();
      const dot = point.getBoundingClientRect();
      studioTooltip.style.left = `${Math.max(0, Math.min(box.width - 260, dot.x - box.x + 12))}px`;
      studioTooltip.style.top = `${dot.y - box.y + 18}px`;
      studioTooltip.hidden = false;
    };
    point.addEventListener("pointerenter", tooltip);
    point.addEventListener("focus", tooltip);
    point.addEventListener("pointerleave", () => { studioTooltip.hidden = true; });
    point.addEventListener("blur", () => { studioTooltip.hidden = true; });
    studioPoints.set(item.id, point);
    document.querySelector("#studio-points").append(point);
  });
  document.querySelector("#studio-legend")?.replaceChildren(...data.clusters.map(type => {
    const button = document.createElement("span");
    const mark = document.createElement("i"); mark.style.background = palette[type.id];
    button.append(mark, document.createTextNode(type.name));
    return button;
  }));

  function drawStudio() {
    if (!studio) return;
    studioTooltip.hidden = true;
    const axes = document.querySelector("#studio-axes"); axes.replaceChildren();
    const labels = document.querySelector("#studio-labels"); labels.replaceChildren();
    const maximum = metricMax[metric];
    const x = value => 60 + value / (view === "profile" ? indexMax : maximum) * 705;
    const y = value => 346 - value / maximum * 304;
    if (view !== "geo") {
      for (let tick = 0; tick <= 4; tick++) {
        const value = maximum * tick / 4;
        const horizontal = (view === "profile" ? indexMax : maximum) * tick / 4;
        axes.append(node("line", {x1: 60, x2: 765, y1: y(value), y2: y(value), class: "studio-grid"}), node("text", {x: 48, y: y(value) + 4, "text-anchor": "end", class: "studio-axis"}, `${number(value, 1)}%`), node("text", {x: x(horizontal), y: 368, "text-anchor": "middle", class: "studio-axis"}, number(horizontal, 1)));
      }
      const indexLabel = data.meta.totalMunicipalities ? "Индекс расходов · 100 = медиана основной панели" : "Индекс расходов · 100 = медиана месяца";
      axes.append(node("text", {x: 60, y: 24, class: "studio-axis-title"}, `${view === "profile" ? "Доля категории" : monthName(snapshot)} · %`), node("text", {x: 765, y: 399, "text-anchor": "end", class: "studio-axis-title"}, view === "profile" ? indexLabel : "Январь 2023 · доля категории, %"));
      if (view === "change") {
        axes.append(node("line", {x1: x(0), x2: x(maximum), y1: y(0), y2: y(maximum), class: "studio-reference"}), node("text", {x: 80, y: 62, class: "studio-region-label"}, "Доля выросла"), node("text", {x: 745, y: 322, "text-anchor": "end", class: "studio-region-label"}, "Доля сократилась"));
      } else {
        axes.append(node("line", {x1: x(100), x2: x(100), y1: 42, y2: 346, class: "studio-reference"}));
      }
    } else {
      for (const lat of [45, 55, 65, 75]) {
        const latitude = 35 + (82 - lat) / 41 * 315;
        axes.append(node("line", {x1: 40, x2: 770, y1: latitude, y2: latitude, class: "studio-grid"}), node("text", {x: 18, y: latitude + 4, class: "studio-axis"}, `${lat}°`));
      }
      axes.append(node("text", {x: 765, y: 399, "text-anchor": "end", class: "studio-axis-title"}, "Положение центров муниципалитетов"));
    }
    items.forEach(item => {
      const longitude = item.lon < 0 ? item.lon + 360 : item.lon;
      const position = view === "geo" ? [40 + (longitude - 19) / 171 * 730, 35 + (82 - item.lat) / 41 * 315] : [x(view === "profile" ? item.history.spendIndex[snapshot] : item.history[metric][0]), y(item.history[metric][snapshot])];
      const point = studioPoints.get(item.id);
      point.setAttribute("transform", `translate(${position.join(" ")})`);
      point.setAttribute("fill", palette[item.trajectory[snapshot]]);
      point.classList.toggle("is-selected", selected?.id === item.id);
      point.setAttribute("tabindex", "0");
      point.setAttribute("aria-label", `${item.name}, ${item.region}: доля ${categories[metric]} ${number(item.history[metric][snapshot], 2)}%, ${monthName(snapshot)}`);
    });
    if (view === "profile") {
      data.clusters.forEach(type => {
        const group = items.filter(item => item.trajectory[snapshot] === type.id);
        if (!group.length) return;
        const cx = x(median(group.map(item => item.history.spendIndex[snapshot])));
        const cy = y(median(group.map(item => item.history[metric][snapshot])));
        labels.append(node("circle", {cx, cy, r: 8, fill: palette[type.id], class: "studio-center"}), node("text", {x: cx + 13, y: cy + 4, class: "studio-type-label"}, `0${type.id}`));
      });
    }
    const title = view === "geo" ? `Где находятся типы · ${monthName(snapshot)}` : view === "profile" ? `Уровень расходов и доля ${categories[metric]}` : `Доля ${categories[metric]} · январь 2023 → ${monthName(snapshot)}`;
    document.querySelector("#studio-title").textContent = title;
    document.querySelector("#studio-chart").setAttribute("aria-label", title);
    const insight = document.querySelector("#studio-insight");
    if (insight) insight.textContent = view === "geo" ? "Цвет — тип в декабре 2024. Карта показывает положение центров, а не площадь территорий." : view === "profile" ? "Крупные точки — медианные показатели каждого типа в декабре 2024." : "На диагонали доля не изменилась. Цвет — тип территории в декабре 2024.";
  }

  function drawCohorts() {
    if (!document.querySelector("#cohort-chart")) return;
    if (!cohortCache.has(metric)) cohortCache.set(metric, cohortSeries(items, data.clusters.length, data.meta.months, metric));
    const series = cohortCache.get(metric);
    const peak = Math.max(...series.flatMap(row => row.values));
    const step = peak <= 10 ? 2 : peak <= 30 ? 5 : 10;
    const maximum = Math.ceil(peak / step) * step;
    const x = index => 52 + index * 32.8;
    const y = value => 275 - value / maximum * 239;
    const chart = document.querySelector("#cohort-chart"); chart.replaceChildren();
    for (let value = 0; value <= maximum; value += step) {
      chart.append(node("line", {x1: 52, x2: x(23), y1: y(value), y2: y(value), class: "chart-grid"}), node("text", {x: 42, y: y(value) + 4, "text-anchor": "end", class: "chart-label"}, `${number(value, 1)}%`));
    }
    chart.append(node("line", {x1: x(snapshot), x2: x(snapshot), y1: 30, y2: 278, class: "cohort-cursor"}));
    series.forEach(row => {
      chart.append(node("path", {d: row.values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" "), fill: "none", stroke: palette[row.id], "stroke-width": 3, class: "cohort-line"}));
      row.values.forEach((value, index) => {
        const point = node("circle", {cx: x(index), cy: y(value), r: index === snapshot ? 6 : 3.5, fill: palette[row.id], class: "cohort-point", "data-month": index, "data-cluster": row.id});
        activate(point, `${data.clusters[row.id - 1].name}, ${monthName(index)}: ${number(value, 2)}%`, () => openAtlas(index)); chart.append(point);
      });
    });
    for (const [index, label] of [[0, "янв 2023"], [12, "янв 2024"], [23, "дек 2024"]]) chart.append(node("text", {x: x(index), y: 311, "text-anchor": index === 23 ? "end" : "start", class: "chart-label"}, label));
    document.querySelector("#cohort-title").textContent = `Доля ${categories[metric]} по типам`;
    chart.setAttribute("aria-label", `Доля ${categories[metric]}, постоянные группы по типам декабря 2024`);
    document.querySelector("#cohort-readout").replaceChildren(...series.map(row => {
      const button = document.createElement("button"); button.type = "button";
      button.style.setProperty("--cohort-color", palette[row.id]);
      const title = document.createElement("strong"); title.textContent = data.clusters[row.id - 1].name;
      const value = document.createElement("span"); value.className = "cohort-value"; value.textContent = `${number(row.values[0], 2)}% → ${number(row.values[snapshot], 2)}%`;
      const note = document.createElement("small"); const delta = row.values[snapshot] - row.values[0];
      note.textContent = `${delta > 0 ? "+" : ""}${number(delta, 2)} п.п. · ${number(row.count)} территорий · янв 2023 → ${monthName(snapshot)}`;
      button.append(title, value, note); button.setAttribute("aria-label", `Показать территории типа «${title.textContent}» в декабре 2024`);
      button.addEventListener("click", () => { changedOnly.checked = false; setMonth(snapshot); filterType(row.id); document.querySelector("#atlas").scrollIntoView({behavior: "smooth"}); });
      return button;
    }));
  }

  const stable = items.filter(item => item.trajectory.every(type => type === item.trajectory[0])).length;
  if (document.querySelector("#story-stable")) {
    document.querySelector("#story-stable").textContent = `${number(stable / items.length * 100)}%`;
    document.querySelector("#story-shift").textContent = `${number(data.historyMedian.marketplace_share[0], 2)}% → ${number(data.historyMedian.marketplace_share[23], 2)}%`;
    const growing = items.filter(item => item.history.marketplace_share[23] > item.history.marketplace_share[0]).length;
    document.querySelector("#story-growth").textContent = `${number(growing)} из ${number(items.length)}`;
  }
  const steps = [...document.querySelectorAll(".story-step")];
  function activateScene(step) {
    view = step.dataset.view || view;
    metric = step.dataset.metric || metric;
    studioTooltip.hidden = true;
    document.querySelectorAll(".story-panel").forEach(panel => { panel.hidden = panel.dataset.panel !== step.dataset.panel; });
    steps.forEach(scene => scene.classList.toggle("is-active", scene === step));
    document.querySelector("#story-progress").textContent = `${String(steps.indexOf(step) + 1).padStart(2, "0")} / ${String(steps.length).padStart(2, "0")}`;
    document.querySelector("#story-chapter").textContent = step.dataset.chapter || "Типы и их изменения";
    const draw = {points: drawStudio, cohorts: drawCohorts, coverage: drawCoverage, distribution: drawDistribution, calendar: drawCalendar, flows: drawFlows};
    draw[step.dataset.panel]?.();
  }
  const observer = new IntersectionObserver(entries => {
    const current = entries.find(entry => entry.isIntersecting);
    if (current) activateScene(current.target);
  }, {rootMargin: "-48% 0px -48% 0px"});
  steps.forEach(step => observer.observe(step));
  if (steps.length) activateScene(steps[0]);

  function paintMap() {
    if (!map) return;
    const values = items.map(item => item.history.spend[month]).sort((a, b) => a - b);
    const low = values[Math.floor(values.length * .05)];
    const high = values[Math.floor(values.length * .95)];
    let count = 0;
    items.forEach(item => {
      const point = points.get(item.id);
      const type = item.trajectory[month];
      let fill = palette[type];
      if (layer.value === "spend") {
        const t = Math.max(0, Math.min(1, (item.history.spend[month] - low) / (high - low || 1)));
        fill = `hsl(${220 - t * 190} 85% ${65 - t * 10}%)`;
      } else if (layer.value === "changes") {
        const changes = item.trajectory.slice(1, month + 1).filter((type, i) => type !== item.trajectory[i]).length;
        fill = changes ? `hsl(${35 - Math.min(changes, 10) * 3} 95% ${72 - Math.min(changes, 10) * 3}%)` : "#456079";
      }
      point.setAttribute("fill", fill);
      point.setAttribute("aria-label", `${item.name}, ${item.region}: ${data.clusters[type - 1].name}, ${monthName(month)}`);
      point.classList.toggle("is-muted", !visible(item));
      point.classList.toggle("has-changed", month > 0 && item.trajectory[month] !== item.trajectory[month - 1]);
      point.setAttribute("tabindex", visible(item) ? "0" : "-1");
      if (visible(item)) count++;
    });
    document.querySelector("#map-status").textContent = `${monthName(month)} · показано ${number(count)} из ${number(items.length)} · сменили тип за месяц: ${month ? stats[month].changed.length : "нет предыдущего месяца"}`;
    document.querySelector(".map-caption").textContent = `Центры муниципалитетов · ${monthName(month)}`;
    document.querySelector("#map-scale").textContent = layer.value === "spend" ? `Синий → оранжевый: ${number(low)} → ${number(high)} ₽. Границы — 5-й и 95-й процентили месяца.` : layer.value === "changes" ? "Серый: без смен · жёлтый → красный: больше смен с января 2023" : "Цвет — тип · обводка — смена типа за месяц";
    document.querySelectorAll(".filter").forEach(button => {
      button.classList.toggle("is-active", Number(button.dataset.cluster) === typeFilter);
      button.setAttribute("aria-pressed", Number(button.dataset.cluster) === typeFilter);
    });
  }

  function drawOverview() {
    const chart = document.querySelector("#overview-chart");
    if (!chart) return;
    chart.replaceChildren(node("text", {x: 0, y: 28, class: "chart-label"}, "100%"), node("text", {x: 0, y: 168, class: "chart-label"}, "0%"));
    stats.forEach((row, index) => {
      const group = node("g", {"data-month": index, class: "month-hit"});
      let bottom = 164;
      data.clusters.forEach(type => {
        const height = row.counts[type.id] / items.length * 140;
        bottom -= height;
        group.append(node("rect", {x: 40 + index * 18, y: bottom, width: 13, height, fill: palette[type.id]}));
      });
      group.append(node("rect", {x: 38 + index * 18, y: 21, width: 17, height: 146, class: "month-outline"}));
      const label = `${monthName(index)}: ${data.clusters.map(type => `${type.name} — ${row.counts[type.id]}`).join(", ")}`;
      group.append(node("title", {}, label));
      activate(group, label, () => openAtlas(index));
      chart.append(group);
    });
    for (const [index, label] of [[0, "янв 2023"], [12, "янв 2024"], [23, "дек 2024"]]) chart.append(node("text", {x: 40 + index * 18, y: 194, "text-anchor": index === 23 ? "end" : "start", class: "chart-label"}, label));
    document.querySelector("#overview-legend").replaceChildren(...data.clusters.map(type => {
      const label = document.createElement("button");
      label.type = "button";
      const mark = document.createElement("i");
      mark.style.background = palette[type.id];
      label.append(mark, document.createTextNode(type.name));
      label.addEventListener("click", () => { changedOnly.checked = false; openAtlas(snapshot); filterType(type.id); });
      label.dataset.cluster = type.id;
      return label;
    }));
    const unchanged = items.filter(item => item.trajectory.every(type => type === item.trajectory[0])).length;
    document.querySelector("#overview-result").textContent = `${number(unchanged)} из ${number(items.length)} территорий не меняли тип за два года. Выберите месяц или тип, чтобы исследовать остальные.`;
  }

  function drawChanges() {
    const chart = document.querySelector("#change-chart");
    if (!chart) return;
    const max = Math.max(...stats.map(row => row.changed.length));
    for (const value of [0, Math.ceil(max / 2), max]) {
      const y = 210 - value / max * 170;
      chart.append(node("line", {x1: 38, y1: y, x2: 610, y2: y, class: "chart-grid"}), node("text", {x: 28, y: y + 4, "text-anchor": "end", class: "chart-label"}, value));
    }
    stats.forEach((row, index) => {
      const bar = node("g", {"data-month": index, class: "change-hit"});
      const height = row.changed.length / max * 170;
      bar.append(node("rect", {x: 42 + index * 23.5, y: 210 - height, width: 17, height: Math.max(height, 3), class: "change-bar"}));
      activate(bar, `${monthName(index)}: ${index ? row.changed.length + " смен типа" : "нет предыдущего месяца"}`, () => { changedOnly.checked = index > 0; typeFilter = 0; setMonth(index); });
      chart.append(bar);
    });
    for (const [index, label] of [[0, "янв 2023"], [12, "янв 2024"], [23, "дек 2024"]]) chart.append(node("text", {x: 42 + index * 23.5, y: 244, "text-anchor": index === 23 ? "end" : "start", class: "chart-label"}, label));
  }

  function renderMatrix() {
    if (!document.querySelector("#transition-matrix")) return;
    document.querySelector("#matrix-month").textContent = month ? `${monthName(month - 1)} → ${monthName(month)}` : "Январь 2023: предыдущего месяца в данных нет";
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    head.append(document.createElement("th"));
    data.clusters.forEach(type => {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = `0${type.id}`; th.title = type.name; th.style.color = palette[type.id]; head.append(th);
    });
    const body = table.createTBody();
    data.clusters.forEach(before => {
      const row = body.insertRow();
      const th = document.createElement("th"); th.scope = "row"; th.textContent = before.name; row.append(th);
      data.clusters.forEach(after => {
        const count = stats[month].matrix[before.id][after.id];
        const button = document.createElement("button");
        button.textContent = number(count);
        button.disabled = !count;
        button.className = before.id === after.id ? "matrix-stay" : "matrix-change";
        button.classList.toggle("is-active", pair?.[0] === before.id && pair?.[1] === after.id);
        button.setAttribute("aria-label", `Из ${before.name} в ${after.name}: ${count} территорий`);
        button.addEventListener("click", () => {
          pair = [before.id, after.id]; typeFilter = 0; changedOnly.checked = false; refresh();
        });
        row.insertCell().append(button);
      });
    });
    document.querySelector("#transition-matrix").replaceChildren(table);
  }

  function renderList() {
    if (!document.querySelector("#transition-list")) return;
    const filtered = items.filter(visible);
    const list = document.querySelector("#transition-list");
    const restricted = pair || changedOnly.checked || typeFilter;
    document.querySelector("#transition-title").textContent = restricted ? `В выделении: ${number(filtered.length)} территорий` : `Смены типа · ${monthName(month)}: ${stats[month].changed.length} территорий`;
    const shown = restricted ? filtered : items.filter(item => stats[month].changed.includes(item.id));
    list.replaceChildren(...shown.map(item => {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = `${item.name} · ${item.region}`;
      button.addEventListener("click", () => { stop(); openMunicipality(item.id); });
      return button;
    }));
    if (!shown.length) list.textContent = month ? "Территорий в этом выделении нет." : "Нельзя определить смену типа без предыдущего месяца.";
  }

  function drawHistory() {
    if (!selected) return;
    const metric = document.querySelector("#history-metric").value;
    const values = selected.history[metric];
    const median = data.historyMedian[metric];
    const max = Math.max(...values, ...median) * 1.1 || 1;
    const x = i => 66 + i * 36;
    const y = value => 208 - value / max * 182;
    const chart = document.querySelector("#history-chart");
    chart.setAttribute("aria-label", `${selected.name}: ${document.querySelector("#history-metric").selectedOptions[0].textContent}, январь 2023 — декабрь 2024; сравнение с медианой выборки`);
    chart.replaceChildren();
    for (const value of [0, max / 2, max]) {
      chart.append(node("line", {x1: 66, x2: 894, y1: y(value), y2: y(value), class: "chart-grid"}), node("text", {x: 56, y: y(value) + 4, "text-anchor": "end", class: "chart-label"}, number(value, metric.endsWith("share") ? 1 : 0)));
    }
    for (const [index, label] of [[0, "янв 2023"], [12, "янв 2024"], [23, "дек 2024"]]) chart.append(node("text", {x: x(index), y: 240, "text-anchor": index === 23 ? "end" : "start", class: "chart-label"}, label));
    chart.append(node("line", {x1: x(month), x2: x(month), y1: 20, y2: 210, class: "history-cursor"}));
    for (const [series, name] of [[median, "history-median"], [values, "history-line"]]) chart.append(node("path", {d: series.map((value, i) => `${i ? "L" : "M"}${x(i)},${y(value)}`).join(" "), class: name}));
    values.forEach((value, index) => {
      const point = node("circle", {cx: x(index), cy: y(value), r: index === month ? 7 : 4, fill: palette[selected.trajectory[index]], class: "history-point"});
      const label = `${monthName(index)}: ${number(value, 2)}, медиана ${number(median[index], 2)}`;
      point.append(node("title", {}, label));
      activate(point, label, () => setMonth(index)); chart.append(point);
    });
    const unit = metric === "spend" ? " ₽" : metric.endsWith("share") ? "%" : "";
    document.querySelector("#history-readout").textContent = `${monthName(month)} · ${selected.name}: ${number(values[month], 2)}${unit} · медиана выборки: ${number(median[month], 2)}${unit}`;
  }

  function updatePassport() {
    if (!selected) return;
    const type = selected.trajectory[month];
    document.querySelector("#passport-date").textContent = `Тип: ${monthName(month)}`;
    document.querySelector("#passport-cluster").textContent = data.clusters[type - 1].name;
    document.querySelector("#passport-dot").style.background = palette[type];
    document.querySelector("#passport-spend").textContent = number(selected.history.spendIndex[month], 1);
    const monthsCurrent = document.querySelector("#passport-months");
    if (monthsCurrent) {
      let run = 1; while (month - run >= 0 && selected.trajectory[month - run] === type) run++;
      monthsCurrent.textContent = run;
    }
    const timeline = document.querySelector("#passport-timeline");
    timeline.replaceChildren(...selected.trajectory.map((type, index) => {
      const button = document.createElement("button"); button.type = "button";
      button.style.background = palette[type]; button.title = `${monthName(index)}: ${data.clusters[type - 1].name}`;
      button.setAttribute("aria-label", button.title); button.setAttribute("aria-pressed", index === month);
      button.classList.toggle("is-current", index === month); button.addEventListener("click", () => setMonth(index)); return button;
    }));
    drawHistory();
  }

  function refresh() {
    const monthInput = document.querySelector("#atlas-month"); if (monthInput) monthInput.value = month;
    const monthLabel = document.querySelector("#month-label"); if (monthLabel) monthLabel.textContent = monthName(month);
    const overviewMonth = document.querySelector("#overview-month"); if (overviewMonth) overviewMonth.textContent = `${monthName(month)} · ${data.clusters.map(type => `${type.name}: ${stats[month].counts[type.id]}`).join(" · ")}`;
    for (const selector of ["#overview-chart [data-month]", "#change-chart [data-month]"]) document.querySelectorAll(selector).forEach(mark => { mark.classList.toggle("is-current", Number(mark.dataset.month) === month); mark.setAttribute("aria-pressed", Number(mark.dataset.month) === month); });
    document.querySelectorAll("#overview-legend button").forEach(button => button.setAttribute("aria-pressed", Number(button.dataset.cluster) === typeFilter));
    const changeReadout = document.querySelector("#change-readout");
    if (changeReadout) changeReadout.textContent = month ? `${monthName(month)}: ${stats[month].changed.length} смен — ${number(stats[month].changed.length / items.length * 100, 1)}% выборки. Нажмите на столбец, чтобы посмотреть эти территории.` : "Для января 2023 нет предыдущего месяца; первая смена наблюдается в феврале.";
    paintMap(); renderMatrix(); renderList(); updatePassport(); drawStudio(); drawCohorts();
  }
  function stop() { clearInterval(timer); timer = undefined; const button = document.querySelector("#month-play"); if (button) { button.textContent = "▶"; button.setAttribute("aria-label", "Проиграть 24 месяца"); } }
  function setMonth(value, playing = false) { if (!playing) stop(); month = Math.max(0, Math.min(23, Number(value))); pair = null; refresh(); }
  function filterType(type) { stop(); typeFilter = type; pair = null; refresh(); }
  document.querySelector("#atlas-month")?.addEventListener("input", event => setMonth(event.target.value));
  document.querySelector("#month-prev")?.addEventListener("click", () => setMonth(month - 1));
  document.querySelector("#month-next")?.addEventListener("click", () => setMonth(month + 1));
  document.querySelector("#month-play")?.addEventListener("click", () => {
    if (timer) { stop(); return; }
    if (month === 23) setMonth(0);
    document.querySelector("#month-play").textContent = "Ⅱ"; document.querySelector("#month-play").setAttribute("aria-label", "Остановить проигрывание");
    timer = setInterval(() => { if (month === 23) stop(); else setMonth(month + 1, true); }, 800);
  });
  document.querySelector("#map-filters")?.addEventListener("click", event => { const button = event.target.closest("[data-cluster]"); if (button) filterType(Number(button.dataset.cluster)); });
  document.querySelector("#changed-only")?.addEventListener("change", () => { stop(); pair = null; refresh(); });
  document.querySelector("#map-layer")?.addEventListener("change", paintMap);
  document.querySelector("#selection-reset")?.addEventListener("click", () => { typeFilter = 0; pair = null; changedOnly.checked = false; refresh(); });
  document.querySelector("#history-metric")?.addEventListener("change", drawHistory);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });

  function changeZoom(factor) {
    const width = Math.max(150, Math.min(1000, zoom[2] * factor));
    const height = width * .44;
    zoom = [zoom[0] + (zoom[2] - width) / 2, zoom[1] + (zoom[3] - height) / 2, width, height];
    map.setAttribute("viewBox", zoom.join(" "));
  }
  document.querySelector("#map-zoom-in")?.addEventListener("click", () => changeZoom(.65));
  document.querySelector("#map-zoom-out")?.addEventListener("click", () => changeZoom(1.5));
  document.querySelector("#map-reset")?.addEventListener("click", () => { zoom = [0, 0, 1000, 440]; map.setAttribute("viewBox", zoom.join(" ")); });
  let drag; let dragged = false;
  map?.addEventListener("pointerdown", event => { if (event.button !== 0) return; drag = {x: event.clientX, y: event.clientY, box: [...zoom]}; dragged = false; });
  map?.addEventListener("pointermove", event => {
    if (!drag) return;
    const dx = event.clientX - drag.x; const dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 5) dragged = true;
    if (dragged) { zoom = [drag.box[0] - dx / map.clientWidth * drag.box[2], drag.box[1] - dy / map.clientHeight * drag.box[3], drag.box[2], drag.box[3]]; map.setAttribute("viewBox", zoom.join(" ")); }
  });
  window.addEventListener("pointerup", () => { drag = null; });
  map?.addEventListener("click", event => { if (dragged) { event.stopPropagation(); event.preventDefault(); dragged = false; } }, true);
  drawNetwork(); drawOverview(); drawChanges(); refresh();
  return {
    month: () => month,
    showMunicipality(item) {
      selected = item;
      if (!visible(item)) { typeFilter = 0; pair = null; changedOnly.checked = false; refresh(); }
      updatePassport();
      drawStudio();
    },
    setMonth,
    filterType
  };
}

if (typeof module !== "undefined") module.exports = {summarizeTrajectories, median, cohortSeries, histogram, percentile, endpointFlows};
