# Installation details

## Supported target

The shell installer is intended for Debian/Ubuntu hosts with `apt`, Python 3,
and normal build tools. It installs into `/opt/fmbcb-rds-multi-scan` by default
and places small command wrappers in `/usr/local/bin`.

## Native tools

The app expects these commands in `PATH`:

- `rx_sdr`
- `csdr`
- `redsea`

The installer checks for each command first. If the command is present, it is
not rebuilt unless `--force-build` is supplied. If the command is missing, the
installer tries to build it from source, unless skipped with one of the
`--skip-*` options.

## APT packages

The installer updates APT metadata once, then installs required and optional
package groups separately. Missing required packages stop the install with a
clear error. Missing optional packages produce warnings and the install
continues.

Required package groups:

- Python: `python3`, `python3-venv`, `python3-pip`, `python3-dev`
- Build: `git`, `build-essential`, `make`, `cmake`, `pkg-config`, `meson`, `ninja-build`
- SDR/DSP libraries: `libusb-1.0-0-dev`, `libfftw3-dev`, `libsndfile1-dev`, `libliquid-dev`
- SoapySDR development/runtime: `soapysdr-tools`, `libsoapysdr-dev`
- Utilities: `usbutils`, `curl`, `ca-certificates`

Optional package group:

- RTL/utility packages that can vary by release: `soapysdr-module-rtlsdr`, `rtl-sdr`, `sox`

The installer installs distro SoapySDR packages. It does not build SoapySDR
itself or install every possible SoapySDR hardware module from source.

## Install path safety

`--prefix`, `--bin-dir`, and `--build-root` must be absolute paths and must not
be broad system directories such as `/`, `/usr`, `/usr/local`, `/opt`, or
`/var`. The same guard applies to `FMB_PREFIX`, `FMB_BIN_DIR`, and
`FMB_BUILD_ROOT`. This protects installer writes and recursive cleanup steps
from accidentally targeting system roots.

## SDRplay

The installer does not bundle SDRplay's proprietary API and does not install
SoapySDRPlay3 automatically. Install the SDRplay API first, then build the
SoapySDRPlay3 module against the installed API and distro SoapySDR development
files.

1. Install this project normally so the distro SoapySDR build dependencies are
   present:

```bash
sudo ./install.sh
```

2. Download the current Linux SDRplay API installer from:

```text
https://www.sdrplay.com/downloads/
```

Choose the API download for Linux. From the directory containing the downloaded
`.run` file:

```bash
chmod +x SDRplay_RSP_API-Linux-*.run
sudo ./SDRplay_RSP_API-Linux-*.run
sudo systemctl enable sdrplay_apiService
sudo systemctl start sdrplay_apiService
systemctl status sdrplay_apiService --no-pager
```

3. Build and install SoapySDRPlay3 from source:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends git cmake build-essential libsoapysdr-dev soapysdr-tools
git clone https://github.com/pothosware/SoapySDRPlay3.git
cd SoapySDRPlay3
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$(nproc)"
sudo cmake --install build
sudo ldconfig
```

4. Verify the SDRplay API service and SoapySDR driver:

```bash
systemctl is-active sdrplay_apiService
SoapySDRUtil --find=sdrplay
SoapySDRUtil --probe="driver=sdrplay"
fmbcb-rds-env-check
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
