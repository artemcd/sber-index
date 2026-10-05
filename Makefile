PYTHON = uv run --locked python

.PHONY: all audit baseline graph validate dynamic compare interpret crosswalk population external site serve

all: site

audit:
	$(PYTHON) scripts/audit_data.py

baseline: audit
	$(PYTHON) scripts/run_baseline.py

graph: baseline
	$(PYTHON) scripts/run_graph_model.py

validate: graph
	$(PYTHON) scripts/validate_model.py

dynamic: validate
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

site: external
	$(PYTHON) scripts/build_site_data.py
	$(PYTHON) scripts/build_external_site_data.py

serve:
	python3 -m http.server 8000 -d site
