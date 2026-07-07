# Troubleshooting

## `rx_sdr` is missing

Run:

```bash
fmbcb-rds-env-check
command -v rx_sdr
```

If it is missing, rerun the installer without `--skip-native-build` and without
`--skip-rx-sdr-build`. If your `rx_sdr` source is from a different fork, set:

```bash
export FMB_RX_TOOLS_REPO=https://your-rx-tools-repo.git
sudo -E ./install.sh --force-build
```

## RTL-SDR is visible in `lsusb` but not usable

Linux DVB drivers may have claimed the device. The checker warns when common
DVB RTL modules are loaded. You can install a blacklist with:

```bash
sudo ./install.sh --install-rtl-blacklist
```

Then reboot or unplug/replug the dongle.

## SDRplay is not found

The installer installs distro SoapySDR packages when available, but it does not
install SDRplay's proprietary API or SoapySDRPlay3. Download the current Linux
SDRplay API from:

```text
https://www.sdrplay.com/downloads/
```

Then install and start the API service:

```bash
chmod +x SDRplay_RSP_API-Linux-*.run
sudo ./SDRplay_RSP_API-Linux-*.run
sudo systemctl enable sdrplay_apiService
sudo systemctl start sdrplay_apiService
systemctl status sdrplay_apiService --no-pager
```

Build SoapySDRPlay3 from source:

```bash
git clone https://github.com/pothosware/SoapySDRPlay3.git
cd SoapySDRPlay3
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$(nproc)"
sudo cmake --install build
sudo ldconfig
```

Then test:

```bash
SoapySDRUtil --find=sdrplay
SoapySDRUtil --probe="driver=sdrplay"
fmbcb-rds-env-check
```

## Redsea builds but runtime cannot find shared libraries

Run:

```bash
sudo ldconfig
redsea --version
```

The installer already runs `ldconfig`, but running it manually can help after
manual source installs.

## Scanner command works as root but not as normal user

This usually points to USB device permissions. Confirm group membership and udev
rules for your SDR hardware. For RTL-SDR, unplug/replug the dongle after udev
rule changes.
