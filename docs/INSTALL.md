# Installation details

## Supported target

The shell installer is intended for Debian/Ubuntu hosts with `apt`, Python 3,
and normal build tools. The primary target is Ubuntu 24.04 LTS. It installs into
`/opt/fmbcb-rds-multi-scan` by default and places small command wrappers in
`/usr/local/bin`.

A normal Ubuntu 24.04 install needs network access for APT, Python package
downloads, and native source checkouts unless all required packages and native
tools are already present and the relevant `--skip-*` options are used. The
SDRplay API installer is bundled in `third-party/` and is not downloaded from
the SDRplay website. Expect the first full install to take several
minutes because SDRplay support, `rx_sdr`, `csdr`, and `redsea` may be installed
or built. When a source build is required, the installer checks the compile
prerequisite packages and installs missing ones through APT. Subsequent installs
are usually faster because existing services, commands, modules, and cached
source checkouts are reused unless `--force-build` is supplied.

One-line bootstrap from a fresh Debian/Ubuntu shell:

```bash
sudo apt-get update && sudo apt-get install -y git ca-certificates && bash -c 'set -Eeuo pipefail; temp_dir=$(mktemp -d); trap "rm -rf \"$temp_dir\"" EXIT; git clone --branch v0.2.0 --depth 1 https://github.com/azwirko/fmbcb-rds-multi-scan.git "$temp_dir/fmbcb-rds-multi-scan"; cd "$temp_dir/fmbcb-rds-multi-scan"; sudo ./install.sh'
```

The installer verifies that the host is Debian/Ubuntu-family and that
`apt-get`, `apt-cache`, and `dpkg` are available before it proceeds. This command
installs the tagged stable release `v0.2.0`; development branch instructions
are intentionally separate from the stable install path.

Quick start from a fresh clone:

```bash
git clone https://github.com/azwirko/fmbcb-rds-multi-scan.git
cd fmbcb-rds-multi-scan
sudo ./install.sh
fmbcb-rds-env-check
fmbcb-rds-multi-scan --help
```

## Native tools

The app expects these commands in `PATH`:

- `rx_sdr`
- `csdr`
- `redsea`

The installer checks for each command first. If the command is present, it is
not rebuilt unless `--force-build` is supplied. If the command is missing, the
installer tries to build it from source, unless skipped with one of the
`--skip-*` options. Before each source build, it checks for the required compile
packages and installs missing ones with APT unless `--skip-build-prereq-apt` is
used.

Native source checkouts live under `--build-root`. Existing git checkouts have
their `origin` URL updated from the configured `FMB_*_REPO` value, then tags are
fetched and pruned. If `FMB_*_REF` is set, the checkout is detached at that ref.
If no ref is set, the checkout is detached at the remote default branch commit
reported by `origin/HEAD`. If a build source path exists but is not a git
checkout, the installer stops unless `--force-build` is used.

## APT packages

The installer updates APT metadata once, then installs the required package
group. Missing required packages stop the install with a clear error.

Required package groups:

- Python: `python3`, `python3-venv`, `python3-pip`, `python3-dev`
- Build: `git`, `build-essential`, `make`, `cmake`, `pkg-config`, `meson`, `ninja-build`
- SDR/DSP libraries: `libusb-1.0-0-dev`, `libfftw3-dev`, `libsndfile1-dev`, `libliquid-dev`
- Soapy module dependencies: `libairspyhf-dev`, `libiio-dev`, `libad9361-dev`, `libhidapi-dev`, `libasound2-dev`
- LimeSDR: `limesuite`, `limesuite-udev`, `liblimesuite-dev`
- SoapySDR development/runtime/modules: `soapysdr-tools`, `libsoapysdr-dev`, `soapysdr-module-all`
- Utilities: `usbutils`, `curl`, `ca-certificates`, `software-properties-common`

The installer installs distro SoapySDR tools, development files, and the
`soapysdr-module-all` bundle. It does not build SoapySDR itself. After these
packages are installed, it enables Ubuntu `universe`, installs LimeSuite and
its udev/development packages, and builds the SoapyAirspyHF, SoapyPlutoSDR, and
SoapyFCDPP modules from source when missing. It also checks SDRplay API service
support and builds the SoapySDRPlay3 hardware module from source when missing.
If the full APT package
step is skipped but a source build is still needed, the installer still installs
missing compile prerequisites through the standard Debian/Ubuntu APT process.
Use `--skip-build-prereq-apt` only when you want missing compile tools to be a
hard error instead.

## Install path safety

`--prefix`, `--bin-dir`, and `--build-root` must be absolute paths and must not
be broad system directories such as `/`, `/usr`, `/usr/local`, `/opt`, or
`/var`. The same guard applies to `FMB_PREFIX`, `FMB_BIN_DIR`, and
`FMB_BUILD_ROOT`. This protects installer writes and recursive cleanup steps
from accidentally targeting system roots.

## Installer preflight

Use `--dry-run` or `--check` to validate installer options and print the install
plan without requiring root and without changing the system:

```bash
./install.sh --dry-run
./install.sh --check --prefix /opt/fmbscan
```

The preflight output includes install paths, APT package groups, SDRplay API and
SoapySDRPlay3 actions, native tool build decisions, configured source
repositories/refs, wrapper paths, the editable rx_sdr profile config path, and
whether full APT, build-prerequisite APT, or native builds are skipped.

## Receiver profile config

The installer seeds `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json` from
`config/rx_sdr_profiles.json` when the file is missing. On reinstall, it preserves
existing profile values and adds newly shipped profile names that are absent. Use
`--config-dir PATH` or `FMB_CONFIG_DIR` to install the editable config somewhere
else. The installed wrapper exports `FMB_RX_SDR_PROFILES` to point the scanner at
the configured file.

Profile gain ranges are intentionally not hard-coded in the shipped defaults.
When gain calibration needs a range, the scanner probes `SoapySDRUtil` for the
selected profile driver and uses the reported gain range when available. If a
driver does not report a usable range, add `gain_min` and `gain_max` overrides
to the profile JSON. `gain_incr` may be an integer or `"auto"`; `"auto"` picks
a step that tests no more than 9 gains per chunk while still including the
maximum gain.

For automatic calibration, the scanner uses one less than the maximum gain
reported by `SoapySDRUtil`, because some drivers report an upper endpoint that
the hardware does not accept. This adjustment applies only to probed ranges
used for calibration; explicit `gain_min` and `gain_max` profile overrides are
used as written.

## Station signal values

The JSONL station summary and RabbitEars signal payload include an `s` field for
each decoded station. It is calculated from the station's successful PI decode
count relative to `11 * chunk_duration_seconds`, using `20 * log10(ratio)`. The
value is capped at `0.0` dBFS when the observed count reaches or exceeds the
theoretical maximum.

## Installed source snapshot

The installer does not copy the entire local working tree into `/opt`. It copies
only the files needed to install and support the package: `LICENSE`, `Makefile`,
`README.md`, `pyproject.toml`, `requirements.txt`, `config/`, `docs/`,
`examples/`, and `src/`. Git metadata, editor files, runtime logs, local JSONL
outputs, virtual environments, and other untracked local files are intentionally
left out of the installed source snapshot.

## Install metadata

Each install writes `${FMB_PREFIX:-/opt/fmbcb-rds-multi-scan}/install-info.env`.
This shell-readable metadata file records the installed app version, install
time, install paths, source repository branch/commit/dirty status, configured
native dependency repos/refs, native dependency checkout commits when present,
SDRplay API settings, SoapySDRPlay3 source details, and resolved `rx_sdr`,
`csdr`, and `redsea` command paths. Include this file when reporting installer
or runtime environment issues.

## Source package

Run `make package` to create a GitHub-friendly source archive and checksum:

```bash
make package
ls -l dist/
```

The package target writes `dist/fmbcb-rds-multi-scan-<version>.tar.gz` and a
matching `.sha256` file. The archive contains the installer scripts, Python
package, docs, examples, config samples, CI workflow, and project metadata.

## Additional SoapySDR modules

The installer checks `SoapySDRUtil --info` for these modules and builds any
missing module from its upstream repository under `--build-root`, installing it
into `/usr/local`:

- `SoapyAirspyHF` for Airspy HF+ (`airspyhf`)
- `SoapyPlutoSDR` for PlutoSDR (`plutosdr`)
- `SoapyFCDPP` for FUNcube Dongle Pro+ (`fcdpp`)

LimeSDR support is installed from Ubuntu packages. On Ubuntu, the installer
enables `universe`, installs `limesuite`, `limesuite-udev`, and
`liblimesuite-dev`, then runs:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The module builds are idempotent and reuse their source checkouts. To skip these
three source builds on a system that does not need the hardware, use:

```bash
sudo ./install.sh --skip-soapy-extra-build
```

Override a module repository or ref with its `FMB_SOAPY_*` environment variables
shown by `sudo ./install.sh --help`. The final `SoapySDRUtil --info` output lists
the loaded module support.

## SDRplay

After the distro SoapySDR packages are installed, the installer automatically
checks SDRplay support unless `--skip-sdrplay` is used.

The SDRplay flow is:

1. Check whether `sdrplay` is active.
2. If the service is not installed, use the bundled
   `third-party/SDRplay_RSP_API-Linux-3.15.2.run` installer. A local absolute
   path may be supplied with `FMB_SDRPLAY_API_INSTALLER`.
3. Mark the `.run` file executable and run it as root. The vendor
   installer may prompt for EULA acceptance; press `Y` only if you accept
   SDRplay's license terms.
4. Enable and start `sdrplay`.
5. Check whether SoapySDR has an SDRplay module loaded.
6. If missing, clone `https://github.com/pothosware/SoapySDRPlay3.git`, build it
   with CMake, install it into `/usr/local`, and run `ldconfig`.
7. At the end of the install, print `SoapySDRUtil --info`, `SoapySDRUtil --find`,
   and `SoapySDRUtil --find=sdrplay` output so the loaded SDR module support and
   detected devices are visible.

Useful controls:

```bash
# Skip all SDRplay API and SoapySDRPlay3 work.
sudo ./install.sh --skip-sdrplay

# Skip only the proprietary SDRplay API installer/service management.
sudo ./install.sh --skip-sdrplay-api

# Skip only the SoapySDRPlay3 source build.
sudo ./install.sh --skip-soapy-sdrplay-build

# Do not auto-install compile prerequisites for source builds.
sudo ./install.sh --skip-build-prereq-apt

# Use a different local SDRplay API installer and pin SoapySDRPlay3.
sudo FMB_SDRPLAY_API_INSTALLER=/path/to/SDRplay_RSP_API-Linux-3.15.2.run \
  FMB_SOAPY_SDRPLAY_REF=<commit-or-tag> \
  ./install.sh
```

For SDRplay runtime verification after installation:

```bash
systemctl is-active sdrplay
SoapySDRUtil --info
SoapySDRUtil --find=sdrplay
SoapySDRUtil --probe="driver=sdrplay"
fmbcb-rds-multi-scan --list-rx-sdr
fmbcb-rds-multi-scan --probe-rx-sdr
fmbcb-rds-env-check
```

Use concrete model profiles such as `--rx-sdr sdrplay-rsp1`,
`--rx-sdr sdrplay-rsp1a`, `--rx-sdr sdrplay-rsp1b`, `--rx-sdr sdrplay-rsp2`,
`--rx-sdr sdrplay-rspduo`, or `--rx-sdr sdrplay-rspdx` for repeatable scans.
The `--rx-sdr sdrplay` alias and `--rx-sdr auto` probe connected SoapySDR
hardware and resolve to a concrete profile when possible. Edit installed
profiles in `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json`.

`SoapySDRUtil --find=sdrplay` and `--probe="driver=sdrplay"` require connected,
powered hardware. A loaded SoapySDRPlay3 module can still be present when no
SDRplay receiver is attached.

## systemd service

A template unit is provided at
`examples/systemd/fmbcb-rds-multi-scan.service.example`. The template runs as a
dedicated `fmbscan` user and writes output under
`/var/lib/fmbcb-rds-multi-scan`. Create those before enabling the service.

1. Create the service user and runtime directory:

```bash
sudo useradd --system --home /var/lib/fmbcb-rds-multi-scan --create-home --shell /usr/sbin/nologin fmbscan
sudo install -d -o fmbscan -g fmbscan -m 0755 /var/lib/fmbcb-rds-multi-scan
```

2. Give the service user access to SDR USB devices. Group names vary by local
udev rules and hardware packages. On Ubuntu/Debian systems, `plugdev` is a
common choice for RTL-SDR-style rules. Add `dialout` only if your local SDR
rules use it.

```bash
sudo usermod -aG plugdev fmbscan
# Optional, only if your local rules require it:
# sudo usermod -aG dialout fmbscan
```

For RTL-SDR devices, install udev rules from your distro package or hardware
vendor when needed. If Linux DVB modules claim the dongle, rerun the installer
with `--install-rtl-blacklist`, then reboot or unplug/replug the device. For
SDRplay, confirm `sdrplay` is active before running this scanner
service.

3. Install and edit the unit file:

```bash
sudo cp examples/systemd/fmbcb-rds-multi-scan.service.example /etc/systemd/system/fmbcb-rds-multi-scan.service
sudo systemctl edit --full fmbcb-rds-multi-scan.service
```

Adjust `ExecStart` for your hardware profile, bandwidth, duration, output path,
and optional RabbitEars tuner key. Do not place secrets or private tuner keys in
the repository copy of the example unit.

4. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fmbcb-rds-multi-scan.service
systemctl status fmbcb-rds-multi-scan.service --no-pager
journalctl -u fmbcb-rds-multi-scan.service -f
```

5. Confirm the output file is owned by the service user and growing:

```bash
sudo ls -l /var/lib/fmbcb-rds-multi-scan/
sudo tail -f /var/lib/fmbcb-rds-multi-scan/rds-scan.jsonl
```

## Custom source pins

Set these before running `install.sh` if you want to pin a fork, tag, or commit:

```bash
export FMB_RX_TOOLS_REPO=https://example.invalid/rx_tools.git
export FMB_RX_TOOLS_REF=v1.2.3
export FMB_CSDR_REF=v0.15
export FMB_REDSEA_REF=v0.21.0
sudo -E ./install.sh
```

Use `sudo -E` only when you intentionally want to preserve these environment
variables into the root installer process.
