PYTHON = uv run --locked python

.PHONY: all audit baseline graph validate dynamic compare interpret site serve

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

site: interpret
	$(PYTHON) scripts/build_site_data.py

serve:
	python3 -m http.server 8000 -d site
