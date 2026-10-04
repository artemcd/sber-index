const colors = {1: "#45c5a1", 2: "#efad55", 3: "#8f83ea"};
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
  document.querySelector("#municipality-search").value = `${municipality.name} — ${municipality.region}`;
  renderTimeline(municipality);
  renderComparables(municipality);
  if (scroll) document.querySelector("#passport").scrollIntoView({behavior: "smooth", block: "center"});
}

function setupSearch() {
  const datalist = document.querySelector("#municipality-list");
  const search = document.querySelector("#municipality-search");
  const searchIndex = new Map();
  const options = document.createDocumentFragment();
  municipalities.forEach(municipality => {
    const label = `${municipality.name} — ${municipality.region}`;
    const option = document.createElement("option");
    option.value = label;
    options.append(option);
    if (!searchIndex.has(label.toLocaleLowerCase("ru"))) searchIndex.set(label.toLocaleLowerCase("ru"), municipality.id);
  });
  datalist.append(options);

  document.querySelector("#search-form").addEventListener("submit", event => {
    event.preventDefault();
    const query = search.value.trim().toLocaleLowerCase("ru");
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

async function start() {
  const response = await fetch("data.json");
  if (!response.ok) throw new Error(`Не удалось загрузить данные: ${response.status}`);
  dataset = await response.json();
  municipalities = dataset.municipalities;
  municipalityById = new Map(municipalities.map(item => [item.id, item]));
  renderSummary();
  renderClusters();
  renderMap();
  renderModels();
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
