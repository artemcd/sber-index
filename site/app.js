const colors = {1: "#41dfc4", 2: "#ffb454", 3: "#a693ff", 4: "#ff7598"};
const modelColors = {
  "KMeans, признаки": "#41dfc4",
  "GMM, признаки": "#ffb454",
  "KMeans, статическая сеть": "#a693ff",
  "KMeans, динамическая сеть": "#ff7598"
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
let explorer;
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
  const agreement = document.querySelector("#matched-ari");
  if (agreement) agreement.textContent = formatNumber(dataset.matchedAgreement.mean, 3);
}

function renderClusters() {
  const container = document.querySelector("#cluster-cards");
  container.innerHTML = dataset.clusters.map(cluster => `
    <article class="type-card" style="--cluster-color: ${colors[cluster.id]}">
      <div class="type-card-head"><span class="type-index">ТИП 0${cluster.id}</span><span class="type-swatch"></span></div>
      <h3>${cluster.name}</h3>
      <p>${cluster.description || descriptions[cluster.id]}</p>
      <dl>
        <div><dt>${formatNumber(cluster.count)}</dt><dd>МО</dd></div>
        ${dataset.meta.totalMunicipalities ? `<div><dt>${formatNumber(cluster.population)}</dt><dd>медиана жителей</dd></div><div><dt>${formatNumber(cluster.urbanShare * 100)}%</dt><dd>городских</dd></div>` : `<div><dt>${formatNumber(cluster.spendIndex, 1)}</dt><dd>индекс расходов</dd></div><div><dt>${cluster.regions}</dt><dd>регионов</dd></div>`}
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
  tooltip.innerHTML = `<strong>${municipality.name}</strong><span>${municipality.region}<br>${dataset.clusters[municipality.trajectory[explorer?.month() ?? 23] - 1].name}</span>`;
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
      "data-id": municipality.id,
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

function renderComparables(municipality) {
  const container = document.querySelector("#passport-comparables");
  if (!container) return;
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
  document.querySelector("#passport-cluster").textContent = dataset.clusters[municipality.cluster - 1].name;
  document.querySelector("#passport-dot").style.background = colors[municipality.cluster];
  document.querySelector("#passport-spend").textContent = formatNumber(municipality.spendIndex, 1);
  document.querySelector("#passport-access").textContent = formatNumber(municipality.marketAccess, 1);
  if (document.querySelector("#passport-months")) document.querySelector("#passport-months").textContent = municipality.monthsCurrent;
  if (document.querySelector("#passport-stability")) document.querySelector("#passport-stability").textContent = municipality.stability;
  if (document.querySelector("#passport-population")) document.querySelector("#passport-population").textContent = formatNumber(municipality.population);
  if (document.querySelector("#passport-urban")) document.querySelector("#passport-urban").textContent = `${formatNumber(municipality.urbanShare * 100, 1)}%`;
  document.querySelector("#municipality-search").value = searchLabels.get(municipality.id);
  explorer?.showMunicipality(municipality);
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
    button.addEventListener("click", () => {
      const signal = dataset.signals.find(item => item.id === Number(button.dataset.signalId));
      const [year, month] = signal.date.split("-").map(Number);
      explorer.setMonth((year - 2023) * 12 + month - 1);
      selectMunicipality(signal.id, true);
    });
  });
}

async function start(population = false) {
  const response = await fetch(population ? "external-data.json?v=5" : "data.json?v=5");
  if (!response.ok) throw new Error(`Не удалось загрузить данные: ${response.status}`);
  dataset = await response.json();
  municipalities = dataset.municipalities;
  municipalityById = new Map(municipalities.map(item => [item.id, item]));
  renderSummary();
  if (document.querySelector("#cluster-cards")) renderClusters();
  if (svg) {
    if (population) document.querySelector("#map-filters").innerHTML = '<button class="filter is-active" data-cluster="0">Все</button>' + dataset.clusters.map(type => `<button class="filter" data-cluster="${type.id}"><span style="background:${colors[type.id]}"></span>${type.name}</button>`).join("");
    renderMap(); setupSearch();
  }
  if (document.querySelector("#model-table")) renderModels();
  if (document.querySelector("#density-table")) renderDensity();
  if (document.querySelector("#cluster-chart")) {
    renderClusterChart();
    document.querySelector("#cluster-chart-metric").addEventListener("change", event => renderClusterChart(event.target.value));
  }
  if (document.querySelector("#map, #studio-chart, #cohort-chart, #change-chart")) explorer = createExplorer(dataset, colors, id => selectMunicipality(id, true));
  if (document.querySelector("#signal-cards")) renderSignals();
  if (svg) {
    const query = new URLSearchParams(window.location.search);
    const month = query.has("month") ? Number(query.get("month")) : 23;
    explorer.setMonth(Number.isInteger(month) && month >= 0 && month <= 23 ? month : 23);
    const cluster = Number(query.get("cluster"));
    const requested = municipalityById.get(Number(query.get("id")));
    const candidate = cluster ? municipalities.find(item => item.trajectory[explorer.month()] === cluster) : municipalityById.get(354);
    selectMunicipality((requested || candidate || municipalities[0]).id);
    if (cluster > 0 && cluster <= dataset.clusters.length) explorer.filterType(cluster);
  }
}

function showError(error) {
  const message = document.createElement("p"); message.className = "page-grid load-error";
  message.textContent = `${error.message}. Запустите локальный HTTP-сервер из папки проекта.`;
  document.querySelector("main").prepend(message);
}

if (document.body.dataset.mode !== "population") start().catch(showError);
