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

When `rx_sdr`, `csdr`, `redsea`, or SoapySDRPlay3 must be built from source, the
installer checks for compile prerequisites such as `git`, `build-essential`,
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
acceptance. Press `Y` only if you accept SDRplay's license terms. If the download
URL changes, override it:

```bash
sudo FMB_SDRPLAY_API_URL=https://www.sdrplay.com/software/SDRplay_RSP_API-Linux-3.15.2.run ./install.sh
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
`fmbcb-rds-multi-scan --probe-rx-sdr`, such as `sdrplay-rsp1a` or
`sdrplay-rspdx`. The `sdrplay` and `auto` profile names depend on live
SoapySDR probing and connected hardware.

`SoapySDRUtil --find=sdrplay` and `--probe="driver=sdrplay"` require connected,
powered hardware. If the service is active and `SoapySDRUtil --info` lists an
SDRplay module, reconnect the receiver and check USB permissions before
rebuilding.

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
