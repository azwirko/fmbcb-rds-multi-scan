# AGENTS.md

## Project

This repository packages `fmbcb-rds-multi-scan`, a Python SDR/RDS FM broadcast scanner for Debian/Ubuntu users.

The installer is expected to:

- install Debian/Ubuntu dependencies;
- build or install `rx_sdr`, `csdr`, and `redsea` when needed;
- create a Python virtual environment;
- install the Python scanner app;
- create wrapper commands;
- provide an environment checker;
- keep the repo suitable for GitHub users cloning and installing locally.

## Target platform

Primary target:

- Ubuntu 24.04 LTS
- Debian/Ubuntu-compatible shell
- Bash for installer scripts
- Python 3 from the OS packages
- RTL-SDR and SDRplay-style `rx_sdr` workflows

## Safety rules

- Do not remove or rewrite the scanner’s core RDS decoding logic unless explicitly asked.
- Do not hard-code personal paths, tuner keys, GitHub usernames, or RabbitEars credentials.
- Do not store secrets in the repo.
- Prefer idempotent installer behavior.
- Prefer clear error messages over silent failures.
- Ask before adding large new dependencies.
- Keep shell scripts compatible with standard Ubuntu 24 packages.

## Before committing changes

Run as many of these as applicable:

```bash
python3 -m py_compile src/fmbcb_rds_multi_scan/*.py
shellcheck install.sh uninstall.sh || true
shfmt -d install.sh uninstall.sh || true
python3 -m pytest || true
```

## Documentation expectations

When changing installer behavior, update:

- README.md
- docs/INSTALL.md
- docs/TROUBLESHOOTING.md
- examples/systemd/fmbcb-rds-multi-scan.service.example if runtime behavior changes

## Git workflow

- Work on feature branches.
- Keep commits small and descriptive.
- Show git diff before committing.
