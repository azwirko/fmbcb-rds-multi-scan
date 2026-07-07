VERSION := $(shell python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
PACKAGE_NAME := fmbcb-rds-multi-scan-$(VERSION)
PACKAGE_FILE := dist/$(PACKAGE_NAME).tar.gz
PACKAGE_FILES := LICENSE Makefile README.md install.sh uninstall.sh pyproject.toml requirements.txt config docs examples src .github
TAR_EXCLUDES := --exclude='*/__pycache__' --exclude='*.pyc' --exclude='*.pyo' --exclude='*.egg-info' --exclude='build' --exclude='dist' --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' --exclude='.venv' --exclude='venv' --exclude='env' --exclude='*.jsonl' --exclude='*.log' --exclude='*.pid' --exclude='*.tmp'

.PHONY: check package clean-package

check:
	python3 -m py_compile src/fmbcb_rds_multi_scan/*.py
	bash -n install.sh uninstall.sh examples/quickstart.sh
	shellcheck install.sh uninstall.sh examples/quickstart.sh
	shfmt -d install.sh uninstall.sh examples/quickstart.sh || true

package: clean-package
	mkdir -p dist
	tar $(TAR_EXCLUDES) --transform='s,^,$(PACKAGE_NAME)/,' -czf $(PACKAGE_FILE) $(PACKAGE_FILES)
	sha256sum $(PACKAGE_FILE) > $(PACKAGE_FILE).sha256
	@printf 'Created %s\n' "$(PACKAGE_FILE)"
	@printf 'Created %s.sha256\n' "$(PACKAGE_FILE)"

clean-package:
	rm -rf dist
