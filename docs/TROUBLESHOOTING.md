# Troubleshooting

## `rx_sdr` is missing

Run:

```bash
fmbcb-rds-env-check
command -v rx_sdr
```

If it is missing, rerun the installer without `--skip-native-build` and without
`--skip-rx-sdr-build`. The installer will install missing compile prerequisites
through APT before building. If your `rx_sdr` source is from a different fork,
set:

```bash
export FMB_RX_TOOLS_REPO=https://your-rx-tools-repo.git
sudo -E ./install.sh --force-build
```


## Source build prerequisites are missing

When `rx_sdr`, `csdr`, `redsea`, SoapySDRPlay3, SoapyAirspyHF, SoapyPlutoSDR,
or SoapyFCDPP must be built from source, the installer checks for compile
prerequisites such as `git`, `build-essential`,
`cmake`, `make`, `pkg-config`, `meson`, `ninja-build`, and related development
headers. Missing packages are installed automatically through APT.

If you used `--skip-build-prereq-apt`, install the listed missing packages
manually or rerun without that option:

```bash
sudo ./install.sh
```

## RTL-SDR is visible in `lsusb` but not usable

Linux DVB drivers may have claimed the device. The checker warns when common
DVB RTL modules are loaded. You can install a blacklist with:

```bash
sudo ./install.sh --install-rtl-blacklist
```

Then reboot or unplug/replug the dongle.

## SDRplay is not found

The installer checks the SDRplay API service and SoapySDRPlay3 module after the
distro SoapySDR packages are installed. Rerun the installer without
`--skip-sdrplay`, `--skip-sdrplay-api`, or `--skip-soapy-sdrplay-build`:

```bash
sudo ./install.sh
```

During SDRplay API installation, the vendor `.run` installer may prompt for EULA
acceptance. Press `Y` only if you accept SDRplay's license terms. The
installer expects `third-party/SDRplay_RSP_API-Linux-3.15.2.run`. To use a
different local copy, provide an absolute path:

```bash
sudo FMB_SDRPLAY_API_INSTALLER=/path/to/SDRplay_RSP_API-Linux-3.15.2.run ./install.sh
```

Then check the service and SoapySDR state:

```bash
systemctl status sdrplay --no-pager
SoapySDRUtil --info
SoapySDRUtil --find=sdrplay
SoapySDRUtil --probe="driver=sdrplay"
fmbcb-rds-multi-scan --list-rx-sdr
fmbcb-rds-multi-scan --probe-rx-sdr
fmbcb-rds-env-check
```

If detection succeeds, use the concrete profile reported by
`fmbcb-rds-multi-scan --probe-rx-sdr`, such as `sdrplay-rsp1a`, `sdrplay-rsp1b`, `sdrplay-rsp2`,
`sdrplay-rspduo`, or `sdrplay-rspdx`. The `sdrplay` and `auto` profile names depend on live
SoapySDR probing and connected hardware.

`SoapySDRUtil --find=sdrplay` and `--probe="driver=sdrplay"` require connected,
powered hardware. If the service is active and `SoapySDRUtil --info` lists an
SDRplay module, reconnect the receiver and check USB permissions before
rebuilding.

## Airspy HF+, PlutoSDR, FCDPP, or LimeSDR is not found

The installer builds the Airspy HF+, PlutoSDR, and FUNcube Pro+ SoapySDR modules
when their drivers are absent from `SoapySDRUtil --info`. It installs LimeSDR
through LimeSuite packages and reloads the udev rules. Check the result with:

```bash
SoapySDRUtil --info
SoapySDRUtil --find
SoapySDRUtil --probe="driver=airspyhf"
SoapySDRUtil --probe="driver=plutosdr"
SoapySDRUtil --probe="driver=fcdpp"
SoapySDRUtil --probe="driver=lime"
```

For LimeSDR, verify that `limesuite`, `limesuite-udev`, and `liblimesuite-dev`
are installed, then reload the rules:

```bash
sudo add-apt-repository universe
sudo apt update
sudo apt install limesuite limesuite-udev liblimesuite-dev
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If a source module fails to build, rerun without
`--skip-build-prereq-apt`; use `--skip-soapy-extra-build` only when the extra
source modules are intentionally not required.

## Bandwidth and Redsea rate resolution

The scanner no longer uses fractional resampling and no longer accepts a
`--redsea-rate` option. It uses `csdr fir_decimate_cc` with an integer factor.
For range-based profiles, the requested bandwidth is resolved downward to an
integer multiple of 171 kHz and Redsea receives 171000 Hz. The startup output
shows both the requested and effective bandwidth.

Airspy and Airspy HF+ profiles require an exact configured bandwidth. The
scanner selects the integer decimation producing the Redsea rate closest to
171000 Hz, subject to the supported range of 166666 through 250000 Hz.

A request can be rejected even when it is inside a profile's nominal range if
no valid integer-only effective rate can be produced. Similarly, some fixed
hardware rates cannot produce a Redsea rate in the permitted range; for
example, 256000 Hz divided by an integer is either 256000 or at most 128000.
Use another configured hardware rate or edit the profile only when the receiver
and resulting sample-rate relationship have been verified.

The scanner must pass Redsea the actual rate produced by integer decimation.
Do not work around a rejection by manually adding `--redsea-rate`; that option
has been removed because a mismatched Redsea rate can corrupt RDS symbol timing.

## Understanding station signal values

Each station row in the JSONL output and RabbitEars payload includes `s`. This
is a capped dBFS value based on successful PI decodes: `20 * log10(count /
(11 * chunk_duration_seconds))`. Values normally range below zero; `0.0` means
the station reached or exceeded the theoretical 11-dec decoded PI codes per
second maximum.

## Redsea builds but runtime cannot find shared libraries

Run:

```bash
sudo ldconfig
redsea --version
```

The installer already runs `ldconfig`, but running it manually can help after
source installs.

## Scanner command works as root but not as normal user

This usually points to USB device permissions. Confirm group membership and udev
rules for your SDR hardware. For RTL-SDR, unplug/replug the dongle after udev
rule changes.

## Report install metadata

When an install or runtime environment problem is not obvious, include:

```bash
fmbcb-rds-env-check
cat /opt/fmbcb-rds-multi-scan/install-info.env
cat /etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json
fmbcb-rds-multi-scan --list-rx-sdr
fmbcb-rds-multi-scan --probe-rx-sdr
```

If you installed with a custom `FMB_PREFIX` or `--prefix`, read
`install-info.env` from that prefix instead. If automatic gain calibration says
no usable gain range exists, connect the SDR and rerun `--probe-rx-sdr`; if the
driver still does not report a gain range, add `gain_min` and `gain_max` to the
profile in `/etc/fmbcb-rds-multi-scan/rx_sdr_profiles.json`.
During automatic calibration, the scanner reduces a probed maximum gain by one
because some drivers report an endpoint that the hardware does not accept.
