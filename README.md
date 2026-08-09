# fmbcb-rds-multi-scan

FM broadcast-band RDS multi-scanner for Debian/Ubuntu systems. The scanner uses
external native SDR/RDS tools (`rx_sdr`, `csdr`, and `redsea`) plus a Python CLI
installed into an isolated virtual environment.

This repo is designed for a shell-installer workflow rather than a `.deb`
package. The installer:

- installs Debian/Ubuntu build/runtime packages when available;
- installs distro SoapySDR tools, development files, and `soapysdr-module-all`;
- checks SDRplay API 3.x service support and builds SoapySDRPlay3 when needed;
- installs missing compile prerequisites before source builds;
- builds and installs missing `rx_sdr`, `csdr`, and `redsea` tools as needed;
- creates `/opt/fmbcb-rds-multi-scan/venv`;
- installs the Python package into that venv from a curated source snapshot;
- writes `/opt/fmbcb-rds-multi-scan/install-info.env` with install/source metadata;
- seeds `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json` if it does not already exist;
- creates `/usr/local/bin/fmbcb-rds-multi-scan` and `/usr/local/bin/fmbcb-rds-env-check` wrappers;
- runs an environment checker at the end.

## Quick install

```bash
git clone https://github.com/azwirko/fmbcb-rds-multi-scan.git
cd fmbcb-rds-multi-scan
sudo ./install.sh
```

Then check the install:

```bash
fmbcb-rds-env-check
fmbcb-rds-multi-scan --help
```

## Example scan

```bash
fmbcb-rds-multi-scan \
  --rx-sdr rtlsdr \
  --bandwidth 2.4M \
  --duration 10 \
  --output ~/rds-scan.jsonl \
  --cycles 1 \
  --show-command
```

For SDRplay, the installer checks the `sdrplay` service, downloads and runs
SDRplay API 3.x when needed, builds SoapySDRPlay3 from source, and prints
`SoapySDRUtil` module/device output at the end. The SDRplay API installer may
prompt for EULA acceptance. Then list or probe the modeled receiver profiles:

```bash
fmbcb-rds-multi-scan --list-rx-sdr
fmbcb-rds-multi-scan --probe-rx-sdr
```

Use a concrete SDRplay model profile for repeatable scans. The legacy
`--rx-sdr sdrplay` alias and `--rx-sdr auto` probe connected SoapySDR hardware
and resolve to a concrete profile when possible. Receiver profiles are stored in
`/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json` after install; reinstall keeps
local edits. Gain ranges are probed from `SoapySDRUtil` when possible, and
automatic calibration uses an `auto` gain step that tests no more than 9 gain
values per chunk.

```bash
fmbcb-rds-multi-scan \
  --rx-sdr sdrplay-rsp1a \
  --bandwidth 5M \
  --duration 10 \
  --output ~/rds-scan.jsonl \
  --cycles 1
```

## Installer options

```bash
sudo ./install.sh --help
```

Common examples:

```bash
# install somewhere other than /opt/fmbcb-rds-multi-scan
# custom install paths must be absolute and must not be broad system roots
sudo ./install.sh --prefix /opt/fmbscan

# do not build native tools; useful when you already installed them manually
sudo ./install.sh --skip-native-build

# prevent automatic APT install of compile prerequisites during source builds
sudo ./install.sh --skip-build-prereq-apt

# rebuild native tools even if commands already exist
sudo ./install.sh --force-build

# skip SDRplay API and SoapySDRPlay3 handling on RTL-only systems
sudo ./install.sh --skip-sdrplay

# optionally blacklist Linux DVB modules that can claim RTL-SDR dongles
sudo ./install.sh --install-rtl-blacklist

# validate paths and print the install plan without changing the system
./install.sh --dry-run
```

## Source package

Build a versioned source tarball and checksum under `dist/`:

```bash
make package
```

## Repository layout

```text
.
├── install.sh
├── uninstall.sh
├── pyproject.toml
├── requirements.txt
├── src/fmbcb_rds_multi_scan/
│   ├── __init__.py
│   ├── __main__.py
│   ├── scanner.py
│   └── check_env.py
├── config/
│   ├── defaults.env.sample
│   └── rx_sdr_profiles.json
├── examples/
│   ├── quickstart.sh
│   └── systemd/fmbcb-rds-multi-scan.service.example
├── docs/
│   ├── INSTALL.md
│   └── TROUBLESHOOTING.md
└── .github/workflows/shellcheck.yml
```

## Runtime notes

- `scanner.py` is the current monolithic scanner module. Later, it can be split
  into smaller modules without changing the installed wrapper command.
- `fmbcb-rds-env-check` verifies command availability, Python dependencies,
  obvious SDR USB visibility, conflicting RTL kernel modules, and SoapySDR
  device discovery.
- `install-info.env` records the installed app version, source commit, install
  paths, native dependency repos/refs, SDRplay installer settings, and native
  checkout commits when present.
- `--rx-sdr` profiles validate `--bandwidth` against their allowed sample-rate
  list. SDRplay profiles are model-specific, such as `sdrplay-rsp1`,
  `sdrplay-rsp1a`, and `sdrplay-rspdx`; `sdrplay` and `auto` use
  `SoapySDRUtil --probe` to resolve connected hardware when possible. Installed
  profiles live in `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json`, with
  `FMB_RX_SDR_PROFILES` available as an override.
- The `rx_sdr` source repo is configurable through `FMB_RX_TOOLS_REPO` because
  deployments may use different forks/builds of the SoapySDR `rx_sdr` tool.

## systemd

A service template is provided at
`examples/systemd/fmbcb-rds-multi-scan.service.example`. See
[docs/INSTALL.md](docs/INSTALL.md) for creating the service user, runtime
directory, hardware access groups, and enabling the unit.

## Uninstall

```bash
sudo ./uninstall.sh
```

The uninstaller removes the app venv and command wrappers. It intentionally
leaves APT packages and native SDR tools installed.
