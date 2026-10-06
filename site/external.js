const colors = {1: "#45c5a1", 2: "#efad55", 3: "#8f83ea", 4: "#f07872"};
const modelColors = {
  "KMeans, признаки": "#45c5a1",
  "GMM, признаки": "#efad55",
  "KMeans, статическая сеть": "#8f83ea",
  "KMeans, динамическая сеть": "#f07872"
};
const svgNamespace = "http://www.w3.org/2000/svg";
const number = (value, digits = 0) => new Intl.NumberFormat("ru-RU", {maximumFractionDigits: digits}).format(value);
const svgElement = (name, attributes = {}) => {
  const element = document.createElementNS(svgNamespace, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
};
const project = (lon, lat) => [35 + (((lon < 0 ? lon + 360 : lon) - 19) / 171) * 930, 28 + ((82 - lat) / 41) * 360];

let dataset;
let municipalities;
let selectedId;
let searchLabels;
const circles = new Map();

function renderTypes() {
  document.querySelector("#stat-municipalities").textContent = number(dataset.meta.totalMunicipalities);
  document.querySelector("#stat-matched").textContent = number(dataset.meta.municipalities);
  document.querySelector("#cluster-cards").innerHTML = dataset.clusters.map(cluster => `
    <article class="type-card" style="--cluster-color: ${colors[cluster.id]}">
      <div class="type-card-head"><span class="type-index">ТИП 0${cluster.id}</span><span class="type-swatch"></span></div>
      <h3>${cluster.name}</h3><p>${cluster.description}</p>
      <dl><div><dt>${number(cluster.count)}</dt><dd>МО</dd></div><div><dt>${number(cluster.population)}</dt><dd>медиана жителей</dd></div><div><dt>${number(cluster.urbanShare * 100)}%</dt><dd>городских</dd></div></dl>
    </article>
  `).join("");
  document.querySelector("#map-filters").innerHTML = [
    '<button class="filter is-active" data-cluster="0">Все</button>',
    ...dataset.clusters.map(cluster => `<button class="filter" data-cluster="${cluster.id}"><span style="background:${colors[cluster.id]}"></span>${cluster.name}</button>`)
  ].join("");
}

function selectMunicipality(id, scroll = false) {
  const item = municipalities.get(Number(id));
  if (!item) return;
  circles.get(selectedId)?.classList.remove("is-selected");
  selectedId = item.id;
  circles.get(selectedId)?.classList.add("is-selected");
  for (const [field, value] of Object.entries({
    region: item.region,
    name: item.name,
    "full-name": item.fullName,
    cluster: dataset.clusters[item.cluster - 1].name,
    population: number(item.population),
    urban: `${number(item.urbanShare * 100, 1)}%`,
    spend: number(item.spendIndex, 1),
    access: number(item.marketAccess, 1)
  })) document.querySelector(`#passport-${field}`).textContent = value;
  document.querySelector("#passport-dot").style.background = colors[item.cluster];
  document.querySelector("#municipality-search").value = searchLabels.get(item.id);
  document.querySelector("#passport-timeline").replaceChildren(...item.trajectory.map((cluster, index) => {
    const mark = document.createElement("span");
    mark.style.background = colors[cluster];
    mark.title = `${2023 + Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, "0")}: ${dataset.clusters[cluster - 1].name}`;
    return mark;
  }));
  if (scroll) document.querySelector("#passport").scrollIntoView({behavior: "smooth", block: "center"});
}

function renderMap() {
  const map = document.querySelector("#map");
  const tooltip = document.querySelector("#map-tooltip");
  for (const lat of [45, 55, 65, 75]) {
    const [, y] = project(30, lat);
    map.append(svgElement("line", {x1: 24, y1: y, x2: 976, y2: y, class: "grid-line"}));
  }
  for (const lon of [30, 60, 90, 120, 150, 180]) {
    const [x] = project(lon, 60);
    map.append(svgElement("line", {x1: x, y1: 22, x2: x, y2: 405, class: "grid-line"}));
  }
  const points = document.createDocumentFragment();
  municipalities.forEach(item => {
    const [cx, cy] = project(item.lon, item.lat);
    const circle = svgElement("circle", {cx, cy, r: 2.6, fill: colors[item.cluster], opacity: .72, class: "municipality", tabindex: 0, role: "button", "aria-label": `${item.name}, ${item.region}: ${dataset.clusters[item.cluster - 1].name}`});
    circle.addEventListener("pointerenter", event => {
      tooltip.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = item.name;
      const detail = document.createElement("span");
      detail.textContent = `${item.region} · ${dataset.clusters[item.cluster - 1].name}`;
      tooltip.append(title, detail);
      tooltip.hidden = false;
      tooltip.style.left = `${event.clientX + 14}px`;
      tooltip.style.top = `${event.clientY + 14}px`;
    });
    circle.addEventListener("pointermove", event => {
      tooltip.style.left = `${event.clientX + 14}px`;
      tooltip.style.top = `${event.clientY + 14}px`;
    });
    circle.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    circle.addEventListener("click", () => selectMunicipality(item.id));
    circle.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") selectMunicipality(item.id);
    });
    circles.set(item.id, circle);
    points.append(circle);
  });
  map.append(points);
  document.querySelector("#map-filters").addEventListener("click", event => {
    const button = event.target.closest("button[data-cluster]");
    if (!button) return;
    const selected = Number(button.dataset.cluster);
    document.querySelectorAll(".filter").forEach(filter => filter.classList.toggle("is-active", filter === button));
    municipalities.forEach(item => circles.get(item.id).classList.toggle("is-muted", selected !== 0 && item.cluster !== selected));
  });
}

function setupSearch() {
  const input = document.querySelector("#municipality-search");
  input.addEventListener("input", () => input.setCustomValidity(""));
  const options = document.createDocumentFragment();
  const lookup = new Map();
  const counts = new Map();
  municipalities.forEach(item => {
    const key = `${item.name} — ${item.region}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  searchLabels = new Map();
  municipalities.forEach(item => {
    const key = `${item.name} — ${item.region}`;
    const label = counts.get(key) > 1 ? `${key} · ${item.fullName}` : key;
    const option = document.createElement("option");
    option.value = label;
    options.append(option);
    lookup.set(label.toLocaleLowerCase("ru"), item.id);
    searchLabels.set(item.id, label);
  });
  document.querySelector("#municipality-list").append(options);
  document.querySelector("#search-form").addEventListener("submit", event => {
    event.preventDefault();
    const query = input.value.trim().toLocaleLowerCase("ru");
    if (!query) {
      input.setCustomValidity("Введите муниципалитет или регион");
      input.reportValidity();
      return;
    }
    const match = municipalities.get(lookup.get(query)) || [...municipalities.values()].find(item =>
      item.name.toLocaleLowerCase("ru").includes(query) || item.region.toLocaleLowerCase("ru").includes(query)
    );
    if (!match) {
      input.setCustomValidity("Муниципалитет не найден в расширенной панели");
      input.reportValidity();
      return;
    }
    input.setCustomValidity("");
    selectMunicipality(match.id, true);
  });
}

function renderModels() {
  document.querySelector("#matched-ari").textContent = number(dataset.matchedAgreement.mean, 3);
  document.querySelector("#model-table").innerHTML = dataset.models.map(model => `
    <tr class="${model.name.includes("динамическая сеть") ? "is-selected" : ""}">
      <td>${model.name.replace("KMeans, ", "")}</td><td>${model.silhouette.toFixed(3)}</td>
      <td>${model.temporalAri.toFixed(3)}</td><td>${model.modularity.toFixed(3)}</td>
    </tr>
  `).join("");
}

function renderDensity() {
  document.querySelector("#density-table").innerHTML = dataset.densityComparison.map(row => `
    <tr><td>${row.name}</td><td>${number(row.coverage * 100, 1)}%</td>
    <td>${number(row.clusters, 1)}</td><td>${number(row.silhouette, 3)}</td></tr>
  `).join("");
}

function renderChart(metric = "silhouette") {
  const chart = document.querySelector("#cluster-chart");
  const rows = dataset.clusterSensitivity;
  const models = [...new Set(rows.map(row => row.model))];
  const values = rows.map(row => row[metric]);
  const padding = (Math.max(...values) - Math.min(...values)) * .12 || .02;
  const lower = Math.min(...values) - padding;
  const upper = Math.max(...values) + padding;
  const x = value => 58 + (value - 2) / 6 * 680;
  const y = value => 252 - (value - lower) / (upper - lower) * 232;
  const percent = ["temporalAri", "minClusterShare"].includes(metric);
  const format = value => percent ? `${(value * 100).toFixed(0)}%` : value.toFixed(3);
  chart.replaceChildren();
  for (let index = 0; index <= 4; index += 1) {
    const value = upper - (upper - lower) * index / 4;
    chart.append(svgElement("line", {x1: 58, y1: y(value), x2: 738, y2: y(value), class: "chart-grid"}));
    const label = svgElement("text", {x: 48, y: y(value) + 4, "text-anchor": "end", class: "chart-label"});
    label.textContent = format(value);
    chart.append(label);
  }
  for (let cluster = 2; cluster <= 8; cluster += 1) {
    const label = svgElement("text", {x: x(cluster), y: 276, "text-anchor": "middle", class: "chart-label"});
    label.textContent = cluster;
    chart.append(label);
  }
  models.forEach(model => {
    const series = rows.filter(row => row.model === model).sort((a, b) => a.clusters - b.clusters);
    chart.append(svgElement("path", {d: series.map((row, index) => `${index ? "L" : "M"}${x(row.clusters)},${y(row[metric])}`).join(" "), stroke: modelColors[model], class: "chart-line"}));
    series.forEach(row => {
      const point = svgElement("circle", {cx: x(row.clusters), cy: y(row[metric]), r: 4.5, fill: modelColors[model], class: "chart-point"});
      const title = svgElement("title");
      title.textContent = `${model}, K=${row.clusters}: ${format(row[metric])}`;
      point.append(title);
      chart.append(point);
    });
  });
  document.querySelector("#cluster-chart-legend").replaceChildren(...models.map(model => {
    const label = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.background = modelColors[model];
    label.append(swatch, document.createTextNode(model));
    return label;
  }));
}

async function start() {
  const response = await fetch("external-data.json?v=3");
  if (!response.ok) throw new Error(`Не удалось загрузить данные: ${response.status}`);
  dataset = await response.json();
  municipalities = new Map(dataset.municipalities.map(item => [item.id, item]));
  renderTypes();
  renderMap();
  setupSearch();
  renderModels();
  renderDensity();
  renderChart();
  document.querySelector("#cluster-chart-metric").addEventListener("change", event => renderChart(event.target.value));
  selectMunicipality(municipalities.has(354) ? 354 : municipalities.keys().next().value);
}

start().catch(error => {
  document.querySelector("#atlas").innerHTML = `<div class="page-grid"><h2>Не удалось открыть атлас</h2><p>${error.message}. Запустите локальный HTTP-сервер из папки проекта.</p></div>`;
});
