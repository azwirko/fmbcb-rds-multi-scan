.PHONY: check package

check:
	python3 -m py_compile src/fmbcb_rds_multi_scan/*.py
	bash -n install.sh uninstall.sh examples/quickstart.sh

package:
	tar --exclude='.git' --exclude='*.tar.gz' -czf ../fmbcb-rds-multi-scan.tar.gz -C .. fmbcb-rds-multi-scan
