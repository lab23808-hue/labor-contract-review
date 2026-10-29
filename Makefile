.PHONY: build-kb test

build-kb:
	python scripts/build_knowledge_base.py

test:
	pytest
