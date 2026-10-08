const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {summarizeTrajectories, median, cohortSeries, histogram, percentile, endpointFlows} = require("../site/overview.js");
const {rosstatPanel} = require("../site/rosstat.js");
const sample = [1, 2, 3].map(id => ({id, history: {spend: Array(12).fill(10).concat(Array(12).fill(30))}}));
const context = {municipalities: [{id: 1, income: [0, 20]}, {id: 2, income: [null, 20]}]};
assert.deepEqual(rosstatPanel(sample, context, "income").map(row => [row.id, row.values, row.spending]), [[1, [0, 20], [10, 30]]]);

assert.equal(median([9, 1, 3]), 3);
assert.equal(median([8, 2]), 5);
assert.equal(percentile([10, 20, 30, 40], .5), 25);
assert.equal(percentile([10, 20, 30, 40], 0), 10);
assert.equal(percentile([10, 20, 30, 40], 1), 40);
assert.deepEqual(histogram([0, 4999, 5000, 10000]).map(bin => bin.count), [2, 1, 1]);
const endpoints = [{id: 1, trajectory: [1, 2, 1]}, {id: 2, trajectory: [1, 1, 2]}];
assert.deepEqual(endpointFlows(endpoints, 2, true), [{from: 1, to: 2, ids: [2]}]);
assert.equal(endpointFlows(endpoints, 2).reduce((sum, row) => sum + row.ids.length, 0), 2);
const cohorts = cohortSeries([
  {trajectory: [1, 2], history: {share: [10, 30]}},
  {trajectory: [2, 2], history: {share: [20, 40]}},
  {trajectory: [2, 1], history: {share: [50, 60]}}
], 2, 2, "share");
assert.deepEqual(cohorts, [{id: 1, count: 1, values: [50, 60]}, {id: 2, count: 2, values: [15, 35]}]);

const example = summarizeTrajectories([
  {id: 1, trajectory: [1, 2, 2]},
  {id: 2, trajectory: [2, 1, 2]},
  {id: 3, trajectory: [1, 1, 1]}
], 2, 3);
assert.deepEqual(example[0].changed, []);
assert.deepEqual(example[1].changed, [1, 2]);
assert.deepEqual(example[1].matrix, [[0, 0, 0], [0, 1, 1], [0, 1, 0]]);
assert.deepEqual(example[2].changed, [2]);

for (const name of ["data.json", "external-data.json"]) {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, "../site", name)));
  const rows = summarizeTrajectories(data.municipalities, data.clusters.length, 24);
  rows.forEach((row, month) => {
    assert.equal(row.counts.reduce((a, b) => a + b), data.municipalities.length);
    assert.equal(row.matrix.flat().reduce((a, b) => a + b), month ? data.municipalities.length : 0);
    const offDiagonal = row.matrix.reduce((sum, line, from) => sum + line.reduce((s, count, to) => s + (from !== to ? count : 0), 0), 0);
    assert.equal(offDiagonal, row.changed.length);
  });
  data.clusters.forEach(type => assert.equal(rows[23].counts[type.id], type.count));
  assert.equal(endpointFlows(data.municipalities, data.clusters.length).reduce((sum, flow) => sum + flow.ids.length, 0), data.municipalities.length);
  assert.equal(endpointFlows(data.municipalities, data.clusters.length, true).reduce((sum, flow) => sum + flow.ids.length, 0), data.municipalities.filter(item => item.trajectory[0] !== item.trajectory[23]).length);
  for (let month = 0; month < 24; month++) {
    const values = data.municipalities.map(item => item.history.spend[month]);
    assert.equal(histogram(values).reduce((sum, bin) => sum + bin.count, 0), data.municipalities.length);
    assert.equal(percentile(values, .5), median(values));
  }
  for (const metric of ["marketplace_share", "grocery_share", "food_service_share", "health_share", "transport_share"]) {
    const series = cohortSeries(data.municipalities, data.clusters.length, 24, metric);
    assert.equal(series.reduce((sum, row) => sum + row.count, 0), data.municipalities.length);
    series.forEach(row => {
      assert.equal(row.count, data.clusters[row.id - 1].count);
      assert.ok(row.values.every(v => Number.isFinite(v) && v >= 0 && v <= 100));
    });
  }
  if (name === "data.json") {
    assert.equal(rows[3].changed.length, 92);
    assert.equal(rows.reduce((sum, row) => sum + row.changed.length, 0), 1174);
  }
  console.log(`${name}: composition, transitions and matrices OK`);
}
