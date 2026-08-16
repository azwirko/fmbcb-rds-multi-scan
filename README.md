# fmbcb-rds-multi-scan

## About This Application

`fmbcb-rds-multi-scan` is a command-line FM broadcast-band scanner for
collecting Radio Data System (RDS) information from multiple stations during a
single scan. It is intended for Linux users who want repeatable, unattended
band surveys and machine-readable results rather than an interactive spectrum
display alone.

### RDS on the FM broadcast band

RDS is the low-rate digital data channel transmitted alongside conventional
stereo FM broadcasts. Depending on the broadcaster, it can contain a station's
program identification (PI) code, program service name (PS), radio text (RT),
traffic or program-type flags, and related station metadata. RDS is not a
separate broadcast band: it is embedded in each FM station's signal, so a
scanner must first find and demodulate individual FM channels before it can
decode their RDS data.

The application scans a configured frequency range by capturing a portion of
the FM band at a selected sample rate, locating station channels in that
capture, and sending each channel through an FM/RDS decoding pipeline. Results
are written as JSONL and can also be uploaded to RabbitEars when configured.
Reception depends on antenna placement, signal strength, frequency spacing,
interference, receiver bandwidth, and whether a station is transmitting useful
RDS data.

### What "multi-scan" means

"Multi-scan" refers to the operation of processing several station channels
from one wideband receiver capture in parallel. It does not mean that one
physical SDR is magically tuned to every frequency at once: the receiver must
support a sufficiently wide instantaneous sample bandwidth, and the host must
have enough CPU, memory, USB or network capacity to run the resulting
`rx_sdr`, `csdr`, and `redsea` pipelines.

For example:

- With `--bandwidth 2.4M`, an RTL-SDR can capture a block of the FM band and
  the scanner can process the stations that fall inside that block. A scan
  covering a larger range moves through additional blocks.
- With `--bandwidth 5M` and `--duration 10`, a compatible SDR can observe a
  wider block for ten seconds, giving the RDS decoders more time to acquire PI,
  PS, and radio-text data from stations in that block.
- With `--cycles 1`, the application performs one pass. More cycles can repeat
  the configured coverage so intermittent or weak RDS data has additional
  opportunities to decode.
- `--rx-sdr` selects the hardware profile, while `--bandwidth` must match a
  sample rate allowed by that profile. Profiles include RTL-SDR, SDRplay,
  Airspy, HackRF, LimeSDR, PlutoSDR, BladeRF, UHD, and other supported SoapySDR
  devices where the required module is installed.

The exact number of simultaneous station pipelines varies with the captured
bandwidth and the stations present. A wider capture can reduce the number of
retunes needed for a survey, but it also increases processing demand. Start
with a modest bandwidth and duration, verify the environment with
`fmbcb-rds-env-check`, and increase them while watching for receiver buffer
overruns and missed decodes.

### How it differs from GUI SDR scanners

Applications such as SDR-Console and SDRSharp are excellent full-featured SDR
receivers, but their normal workflow is interactive: the user tunes one
station or channel, views it, and uses an RDS display or plugin to decode that
station. Even where scanning plugins are available, they commonly retune or
check stations sequentially. A full-band survey can therefore take a long
time, and a short dwell may not give RDS enough time to acquire reliable data.

This project uses a different workflow. It is a focused batch scanner that
combines SoapySDR hardware access with native command-line signal-processing
tools and multiple decoder processes. It can collect several stations from
each wideband capture, repeat the survey, calibrate receiver gain by chunk,
and emit structured results suitable for scripts, archives, or uploads. It
does not replace a GUI SDR for live listening, spectrum exploration, recording,
or manual tuning, and it cannot overcome weak reception or hardware and host
throughput limits.

### What users should expect

- A Debian/Ubuntu-oriented installer that installs or builds the native SDR
  tools and SoapySDR modules, then creates an isolated Python environment.
- Hardware-specific profiles with supported bandwidth ranges or exact bandwidth
  values and gain behavior;
  installed profiles can be viewed and edited at
  `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json`.
- Automatic gain calibration for scan chunks, including probed hardware gain
  limits where available.
- JSONL station output containing decoded RDS fields and a capped relative
  signal indication (`s`, reported as dBFS in console output).
- Optional RabbitEars station uploads and repeatable command-line operation
  suitable for scheduled or headless systems.

For range-based profiles, the requested integer bandwidth is resolved downward
to an integer multiple of 171 kHz so the integer FIR decimator produces the
fixed 171 kHz Redsea input. Airspy Mini and Airspy R2 use exact profile bandwidth values. The generic
`--rx-sdr airspy` alias probes the advertised sample rates to select the
matching model. Fixed-rate profiles choose the integer-decimated Redsea rate
at or above 171000 Hz, constrained not to exceed 192000 Hz. The startup
output shows the requested and effective rates.

The project is best suited to users who already have an FM antenna and SDR,
want to compare coverage or station metadata across a band, and are comfortable
adjusting bandwidth, duration, gain, and hardware setup for their system.

FM broadcast-band RDS multi-scanner for Debian/Ubuntu systems. The scanner uses
external native SDR/RDS tools (`rx_sdr`, `csdr`, and `redsea`) plus a Python CLI
installed into an isolated virtual environment.

This repo is designed for a shell-installer workflow rather than a `.deb`
package. The installer:

- installs Debian/Ubuntu build/runtime packages when available;
- installs distro SoapySDR tools, development files, and `soapysdr-module-all`;
- enables Ubuntu `universe` and installs LimeSuite support and udev rules;
- builds missing SoapyAirspyHF, SoapyPlutoSDR, and SoapyFCDPP modules;
- checks SDRplay API 3.x service support and builds SoapySDRPlay3 when needed;
- installs missing compile prerequisites before source builds;
- builds and installs missing `rx_sdr`, `csdr`, and `redsea` tools as needed;
- creates `/opt/fmbcb-rds-multi-scan/venv`;
- installs the Python package into that venv from a curated source snapshot;
- writes `/opt/fmbcb-rds-multi-scan/install-info.env` with install/source metadata;
- merges `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json` by default, with
  overwrite and separate-new-file profile update modes;
- creates `/usr/local/bin/fmbcb-rds-multi-scan` and `/usr/local/bin/fmbcb-rds-env-check` wrappers;
- installs a modprobe blacklist for the MSI/Mirics kernel modules that can
  claim MiriSDR and SDRplay-compatible devices;
- runs an environment checker at the end.

## Quick install

For a one-line bootstrap on Debian/Ubuntu, copy and run:

```bash
sudo apt-get update && sudo apt-get install -y git ca-certificates && bash -c 'set -Eeuo pipefail; temp_dir=$(mktemp -d); trap "rm -rf \"$temp_dir\"" EXIT; git clone --branch v0.2.1 --depth 1 https://github.com/azwirko/fmbcb-rds-multi-scan.git "$temp_dir/fmbcb-rds-multi-scan"; cd "$temp_dir/fmbcb-rds-multi-scan"; sudo ./install.sh'
```

The installer verifies that the host is Debian/Ubuntu-family and that
`apt-get`, `apt-cache`, and `dpkg` are available before it proceeds. This command installs the
`v0.2.1` release, including the local SDRplay API installer.

For a manual clone workflow:

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

## Tested hardware in v0.2.1

The following hardware has been tested with this release. The profile name is
passed to `--rx-sdr`; hardware-specific USB, network, firmware, and udev setup
may still be required.

| Hardware | SoapySDR driver/profile |
| --- | --- |
| SDRplay RSP1 | `sdrplay-rsp1` |
| SDRplay RSP1A | `sdrplay-rsp1a` |
| SDRplay RSPdx | `sdrplay-rspdx` |
| RTL-SDR | `rtlsdr` |
| ADALM-Pluto | `plutosdr` |
| LibreSDR/ZynqSDR | `plutosdr` |
| LimeSDR Mini | `lime` |
| Airspy Mini | `airspy-mini` |
| Airspy R2 | `airspy-r2` |
| Airspy HF+ | `airspyhf` |
| Pluto+ SDR | `plutosdr` |
| HackRF One | `hackrf` |

This table records hardware tested by the project maintainer; it is not a
guarantee that every revision, firmware version, host, or sample rate behaves
identically. Use `fmbcb-rds-multi-scan --probe-rx-sdr` to inspect detected
SoapySDR hardware before scanning.

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

For SDRplay, the installer checks the `sdrplay` service, runs the bundled
SDRplay API 3.x installer from `third-party/` when needed, builds
SoapySDRPlay3 from source, and prints
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
local edits and adds newly shipped profile names. Gain ranges are probed from
`SoapySDRUtil` when possible, and
automatic calibration uses an `auto` gain step that tests no more than 9 gain
values per chunk.
For automatic calibration, a probed maximum is reduced by one because some
drivers report an upper endpoint that the hardware does not accept; explicit
profile overrides are used as written.
Profiles may set `gain_calibration` to `false` and provide a
`gain_default` when reported gain controls do not apply to the selected antenna
path. Such profiles skip calibration; `--rx-gain` still overrides the profile
default.

Station summaries include `s`, a capped dBFS signal value calculated as
`20 * log10(pi_decodes / (11 * chunk_duration_seconds))`. A station at or above
the theoretical 11 PI decodes per second maximum is reported as `s: 0.0`.

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
- `--rx-sdr` profiles validate `--bandwidth` against their allowed bandwidth
  range or exact-value list. SDRplay profiles are model-specific, such as `sdrplay-rsp1`, `sdrplay-rsp1a`, `sdrplay-rsp1b`, `sdrplay-rsp2`,
  `sdrplay-rspduo`, and `sdrplay-rspdx`; `sdrplay` and `auto` use
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
