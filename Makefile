# HORUS: see it, check it, test it.
PY ?= python3

console:            ## the 3D campus console on http://127.0.0.1:8030/campus3d/
	$(PY) dashboard/campus3d/serve.py

verify:             ## recompute every headline number from the raw evidence (stdlib only)
	$(PY) verify.py

test:               ## runtime contract, v3.14 pipeline, console and dashboard tests (needs requirements.txt)
	$(PY) -m pytest -q stack/tests/test_selector_runtime_v314.py   # own process: the runtime refuses a backend imported from elsewhere
	$(PY) -m pytest -q release/test_radio_options.py pipeline/tests/test_v314.py pipeline/tests/test_measured_v314.py \
	    dashboard/tests/test_results_current.py
	$(PY) dashboard/campus3d/tests/test_campus3d.py

.PHONY: console verify test
