.PHONY: build-kb gen-evals eval test

build-kb:
	python scripts/build_knowledge_base.py

gen-evals:
	python scripts/generate_eval_contracts.py

eval:
	python scripts/run_eval_samples.py --fake-llm

test:
	pytest
