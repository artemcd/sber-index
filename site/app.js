const colors = {1: "#45c5a1", 2: "#efad55", 3: "#8f83ea"};
const modelColors = {
  "KMeans, признаки": "#45c5a1",
  "GMM, признаки": "#efad55",
  "KMeans, статическая сеть": "#8f83ea",
  "KMeans, динамическая сеть": "#f07872"
};
const descriptions = {
  1: "Ниже медианы по общим расходам, заметно выше роль маркетплейсов и повседневных покупок.",
  2: "Расходы выше медианы при сравнительно низкой доступности внешних рынков.",
  3: "Высокие расходы и доступность рынков, повышенная доля общепита, транспорта и здоровья."
};

let dataset;
let municipalities;
let municipalityById;
let circlesById = new Map();
let activeCluster = 0;
let selectedId;
let searchLabels;

const svg = document.querySelector("#map");
const tooltip = document.querySelector("#map-tooltip");
const svgNamespace = "http://www.w3.org/2000/svg";

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(svgNamespace, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function project(lon, lat) {
  const longitude = lon < 0 ? lon + 360 : lon;
  return [35 + ((longitude - 19) / 171) * 930, 28 + ((82 - lat) / 41) * 360];
}

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat("ru-RU", {maximumFractionDigits: digits}).format(value);
}

function renderSummary() {
  document.querySelector("#stat-municipalities").textContent = formatNumber(dataset.meta.municipalities);
  document.querySelector("#stat-core").textContent = `${Math.round(dataset.meta.coreShare * 100)}%`;
  document.querySelector("#stat-transitions").textContent = dataset.meta.persistentTransitions;
}

function renderClusters() {
  const container = document.querySelector("#cluster-cards");
  container.innerHTML = dataset.clusters.map(cluster => `
    <article class="type-card" style="--cluster-color: ${colors[cluster.id]}">
      <div class="type-card-head"><span class="type-index">ТИП 0${cluster.id}</span><span class="type-swatch"></span></div>
      <h3>${cluster.name}</h3>
      <p>${descriptions[cluster.id]}</p>
      <dl>
        <div><dt>${formatNumber(cluster.count)}</dt><dd>МО</dd></div>
        <div><dt>${formatNumber(cluster.spendIndex, 1)}</dt><dd>индекс расходов</dd></div>
        <div><dt>${cluster.regions}</dt><dd>регионов</dd></div>
      </dl>
    </article>
  `).join("");
}

function renderGrid() {
  [45, 55, 65, 75].forEach(latitude => {
    const [, y] = project(30, latitude);
    svg.append(svgElement("line", {x1: 24, y1: y, x2: 976, y2: y, class: "grid-line"}));
    const label = svgElement("text", {x: 28, y: y - 6, class: "map-label"});
    label.textContent = `${latitude}°`;
    svg.append(label);
  });
  [30, 60, 90, 120, 150, 180].forEach(longitude => {
    const [x] = project(longitude, 60);
    svg.append(svgElement("line", {x1: x, y1: 22, x2: x, y2: 405, class: "grid-line"}));
  });
}

function showTooltip(event, municipality) {
  tooltip.innerHTML = `<strong>${municipality.name}</strong><span>${municipality.region}<br>${municipality.clusterName}</span>`;
  tooltip.hidden = false;
  tooltip.style.left = `${event.clientX + 14}px`;
  tooltip.style.top = `${event.clientY + 14}px`;
}

function renderMap() {
  svg.replaceChildren();
  renderGrid();
  const points = document.createDocumentFragment();
  municipalities.forEach(municipality => {
    const [cx, cy] = project(municipality.lon, municipality.lat);
    const circle = svgElement("circle", {
      cx,
      cy,
      r: 2.6,
      fill: colors[municipality.cluster],
      opacity: .72,
      class: "municipality",
      tabindex: 0,
      role: "button",
      "aria-label": `${municipality.name}, ${municipality.region}: ${municipality.clusterName}`
    });
    circle.addEventListener("pointerenter", event => showTooltip(event, municipality));
    circle.addEventListener("pointermove", event => showTooltip(event, municipality));
    circle.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    circle.addEventListener("click", () => selectMunicipality(municipality.id));
    circle.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") selectMunicipality(municipality.id);
    });
    circlesById.set(municipality.id, circle);
    points.append(circle);
  });
  svg.append(points);
}

function applyFilter(cluster) {
  activeCluster = cluster;
  document.querySelectorAll(".filter").forEach(button => {
    button.classList.toggle("is-active", Number(button.dataset.cluster) === cluster);
  });
  municipalities.forEach(municipality => {
    circlesById.get(municipality.id).classList.toggle(
      "is-muted",
      cluster !== 0 && municipality.cluster !== cluster
    );
  });
}

function renderTimeline(municipality) {
  const timeline = document.querySelector("#passport-timeline");
  timeline.replaceChildren(...municipality.trajectory.map((cluster, index) => {
    const month = index + 1;
    const date = month <= 12 ? `2023-${String(month).padStart(2, "0")}` : `2024-${String(month - 12).padStart(2, "0")}`;
    const element = document.createElement("span");
    element.style.background = colors[cluster];
    element.title = `${date}: ${dataset.clusters[cluster - 1].name}`;
    return element;
  }));
}

function renderComparables(municipality) {
  const container = document.querySelector("#passport-comparables");
  container.replaceChildren(...municipality.comparables.map(peer => {
    const button = document.createElement("button");
    button.className = "comparable";
    button.innerHTML = `<strong>${peer.name}</strong><span>${peer.region}</span>`;
    button.addEventListener("click", () => selectMunicipality(peer.id));
    return button;
  }));
}

function selectMunicipality(id, scroll = false) {
  const municipality = municipalityById.get(Number(id));
  if (!municipality) return;
  if (selectedId) circlesById.get(selectedId)?.classList.remove("is-selected");
  selectedId = municipality.id;
  circlesById.get(selectedId)?.classList.add("is-selected");

  document.querySelector("#passport-region").textContent = municipality.region;
  document.querySelector("#passport-name").textContent = municipality.name;
  document.querySelector("#passport-full-name").textContent = municipality.fullName;
  document.querySelector("#passport-cluster").textContent = municipality.clusterName;
  document.querySelector("#passport-dot").style.background = colors[municipality.cluster];
  document.querySelector("#passport-spend").textContent = formatNumber(municipality.spendIndex, 1);
  document.querySelector("#passport-access").textContent = formatNumber(municipality.marketAccess, 1);
  document.querySelector("#passport-months").textContent = municipality.monthsCurrent;
  document.querySelector("#passport-stability").textContent = municipality.stability;
  document.querySelector("#municipality-search").value = searchLabels.get(municipality.id);
  renderTimeline(municipality);
  renderComparables(municipality);
  if (scroll) document.querySelector("#passport").scrollIntoView({behavior: "smooth", block: "center"});
}

function setupSearch() {
  const datalist = document.querySelector("#municipality-list");
  const search = document.querySelector("#municipality-search");
  const searchIndex = new Map();
  const options = document.createDocumentFragment();
  const counts = new Map();
  municipalities.forEach(item => {
    const key = `${item.name} — ${item.region}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  searchLabels = new Map();
  municipalities.forEach(municipality => {
    const key = `${municipality.name} — ${municipality.region}`;
    const label = counts.get(key) > 1 ? `${key} · ${municipality.fullName}` : key;
    const option = document.createElement("option");
    option.value = label;
    options.append(option);
    searchIndex.set(label.toLocaleLowerCase("ru"), municipality.id);
    searchLabels.set(municipality.id, label);
  });
  datalist.append(options);
  search.addEventListener("input", () => search.setCustomValidity(""));

  document.querySelector("#search-form").addEventListener("submit", event => {
    event.preventDefault();
    const query = search.value.trim().toLocaleLowerCase("ru");
    if (!query) {
      search.setCustomValidity("Введите муниципалитет или регион");
      search.reportValidity();
      return;
    }
    const exactId = searchIndex.get(query);
    const match = exactId ? municipalityById.get(exactId) : municipalities.find(item =>
      item.name.toLocaleLowerCase("ru").includes(query) || item.region.toLocaleLowerCase("ru").includes(query)
    );
    if (!match) {
      search.setCustomValidity("Муниципалитет не найден");
      search.reportValidity();
      return;
    }
    search.setCustomValidity("");
    selectMunicipality(match.id, true);
  });
}

function renderModels() {
  document.querySelector("#model-table").innerHTML = dataset.models.map(model => {
    const selected = model.name.includes("динамическая сеть");
    return `<tr class="${selected ? "is-selected" : ""}">
      <td>${model.name.replace("KMeans, ", "")}</td>
      <td>${model.silhouette.toFixed(3)}</td>
      <td>${model.temporalAri.toFixed(3)}</td>
      <td>${model.modularity.toFixed(3)}</td>
    </tr>`;
  }).join("");
}

function renderDensity() {
  document.querySelector("#density-table").innerHTML = dataset.densityComparison.map(row => `
    <tr><td>${row.name}</td><td>${formatNumber(row.coverage * 100, 1)}%</td>
    <td>${formatNumber(row.clusters, 1)}</td><td>${formatNumber(row.silhouette, 3)}</td></tr>
  `).join("");
}

function renderClusterChart(metric = "silhouette") {
  const chart = document.querySelector("#cluster-chart");
  const legend = document.querySelector("#cluster-chart-legend");
  const rows = dataset.clusterSensitivity;
  const models = [...new Set(rows.map(row => row.model))];
  const values = rows.map(row => row[metric]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const padding = (maxValue - minValue) * .12 || .02;
  const lower = minValue - padding;
  const upper = maxValue + padding;
  const left = 58;
  const right = 738;
  const top = 20;
  const bottom = 252;
  const clusters = [...new Set(rows.map(row => row.clusters))].sort((a, b) => a - b);
  const x = value => left + (value - clusters[0]) / (clusters.at(-1) - clusters[0]) * (right - left);
  const y = value => bottom - (value - lower) / (upper - lower) * (bottom - top);
  const percent = ["temporalAri", "minClusterShare"].includes(metric);
  const format = value => percent ? `${(value * 100).toFixed(0)}%` : value.toFixed(3);

  chart.replaceChildren();
  for (let index = 0; index <= 4; index += 1) {
    const value = upper - (upper - lower) * index / 4;
    const line = svgElement("line", {x1: left, y1: y(value), x2: right, y2: y(value), class: "chart-grid"});
    const label = svgElement("text", {x: left - 10, y: y(value) + 4, "text-anchor": "end", class: "chart-label"});
    label.textContent = format(value);
    chart.append(line, label);
  }
  clusters.forEach(cluster => {
    const label = svgElement("text", {x: x(cluster), y: bottom + 24, "text-anchor": "middle", class: "chart-label"});
    label.textContent = cluster;
    chart.append(label);
  });

  models.forEach(model => {
    const series = rows.filter(row => row.model === model).sort((a, b) => a.clusters - b.clusters);
    const path = svgElement("path", {
      d: series.map((row, index) => `${index ? "L" : "M"}${x(row.clusters)},${y(row[metric])}`).join(" "),
      stroke: modelColors[model],
      class: "chart-line"
    });
    chart.append(path);
    series.forEach(row => {
      const point = svgElement("circle", {cx: x(row.clusters), cy: y(row[metric]), r: 4.5, fill: modelColors[model], class: "chart-point"});
      const title = svgElement("title");
      title.textContent = `${model}, K=${row.clusters}: ${format(row[metric])}`;
      point.append(title);
      chart.append(point);
    });
  });

  legend.replaceChildren(...models.map(model => {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.background = modelColors[model];
    item.append(swatch, document.createTextNode(model));
    return item;
  }));
}

function formatMonth(value) {
  const [year, month] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("ru-RU", {month: "long", year: "numeric"})
    .format(new Date(Date.UTC(year, month - 1, 1)));
}

function renderSignals() {
  document.querySelector("#signal-cards").innerHTML = dataset.signals.map((signal, index) => `
    <article class="signal-card" style="--from-color: ${colors[signal.fromCluster]}; --to-color: ${colors[signal.toCluster]}">
      <div class="signal-card-head"><span>НАБЛЮДЕНИЕ 0${index + 1}</span><strong>${formatMonth(signal.date)}</strong></div>
      <h3>${signal.name}</h3>
      <p class="signal-region">${signal.region}</p>
      <div class="signal-path">
        <div><span></span><small>Было</small><strong>${signal.fromName}</strong></div>
        <b>→</b>
        <div><span></span><small>Стало</small><strong>${signal.toName}</strong></div>
      </div>
      <dl class="signal-facts">
        <div><dt>${signal.months}</dt><dd>месяцев подряд</dd></div>
        <div><dt>${formatNumber(signal.margin * 100, 1)}%</dt><dd>относительный отрыв</dd></div>
      </dl>
      <button class="signal-open" data-signal-id="${signal.id}">Открыть в атласе</button>
    </article>
  `).join("");
  document.querySelectorAll("[data-signal-id]").forEach(button => {
    button.addEventListener("click", () => selectMunicipality(button.dataset.signalId, true));
  });
}

async function start() {
  const response = await fetch("data.json?v=3");
  if (!response.ok) throw new Error(`Не удалось загрузить данные: ${response.status}`);
  dataset = await response.json();
  municipalities = dataset.municipalities;
  municipalityById = new Map(municipalities.map(item => [item.id, item]));
  renderSummary();
  renderClusters();
  renderMap();
  renderSignals();
  renderModels();
  renderDensity();
  renderClusterChart();
  document.querySelector("#cluster-chart-metric").addEventListener("change", event => renderClusterChart(event.target.value));
  setupSearch();
  document.querySelector("#map-filters").addEventListener("click", event => {
    const button = event.target.closest("button[data-cluster]");
    if (button) applyFilter(Number(button.dataset.cluster));
  });
  selectMunicipality(municipalityById.has(354) ? 354 : municipalities[0].id);
}

start().catch(error => {
  document.querySelector("#atlas").innerHTML = `<div class="page-grid"><h2>Не удалось открыть атлас</h2><p>${error.message}. Запустите локальный HTTP-сервер из папки проекта.</p></div>`;
});
