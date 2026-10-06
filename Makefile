PYTHON = uv run --locked python

.PHONY: all audit baseline graph validate dynamic compare interpret crosswalk population external density site check serve

all: site

audit:
	$(PYTHON) scripts/audit_data.py

baseline: audit
	$(PYTHON) scripts/run_baseline.py

graph: baseline
	$(PYTHON) scripts/run_graph_model.py

validate: graph
	$(PYTHON) scripts/validate_model.py

dynamic: graph
	$(PYTHON) scripts/run_dynamic_model.py

compare: dynamic
	$(PYTHON) scripts/compare_models.py

interpret: compare
	$(PYTHON) scripts/interpret_clusters.py

crosswalk: interpret
	$(PYTHON) scripts/build_oktmo_crosswalk.py

population: crosswalk
	$(PYTHON) scripts/prepare_population.py

external: population
	$(PYTHON) scripts/run_population_model.py

density: external
	$(PYTHON) scripts/compare_hdbscan.py

site: density
	$(PYTHON) scripts/build_site_data.py
	$(PYTHON) scripts/build_external_site_data.py
	python3 scripts/check_site.py

check:
	python3 scripts/check_site.py

serve:
	python3 -m http.server 8000 -d site
