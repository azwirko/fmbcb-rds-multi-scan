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

The installer uses an availability check before installing optional package
names, so the same script can be used across Debian/Ubuntu releases where some
package names differ.

Core package groups:

- Python: `python3`, `python3-venv`, `python3-pip`, `python3-dev`
- Build: `git`, `build-essential`, `make`, `cmake`, `pkg-config`, `meson`, `ninja-build`
- SDR/DSP libraries: `libusb-1.0-0-dev`, `libfftw3-dev`, `libsndfile1-dev`, `libliquid-dev`
- SoapySDR/RTL support when available: `soapysdr-tools`, `libsoapysdr-dev`, `soapysdr-module-rtlsdr`, `rtl-sdr`
- Utilities: `usbutils`, `sox`, `curl`, `ca-certificates`

## SDRplay

The installer does not bundle SDRplay's proprietary API. Install SDRplay's
current Linux API and SoapySDRPlay module first, then verify:

```bash
SoapySDRUtil --find=sdrplay
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
