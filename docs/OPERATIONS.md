# Application Operations Reference

This document describes every runtime argument accepted by
`fmbcb-rds-multi-scan`, its effect, and common combinations. The command
requires `--rx-sdr` and `--bandwidth`; all other runtime settings have defaults
unless stated otherwise.

## Minimal command

```bash
fmbcb-rds-multi-scan --rx-sdr rtlsdr --bandwidth 2.4M
```

This uses a 15-second chunk duration and creates an append-only file similar to
`rds-scan-rtlsdr-2400000Hz-15s.jsonl` in the current directory.

## Core scan arguments

| Argument | Default | Effect |
| --- | --- | --- |
| `--rx-sdr PROFILE` | required | Selects the SoapySDR/rx_sdr profile. Use a concrete model such as `sdrplay-rsp1a`, or an alias such as `sdrplay`, `airspy`, or `auto` when supported. The resolved concrete profile is used in the default output filename. |
| `--bandwidth VALUE` | required | Sets the requested SDR capture bandwidth, such as `2.4M`, `5M`, or `768k`. Range profiles resolve to an integer FIR decimation; fixed-rate profiles require an exact supported value. |
| `--duration SECONDS` | `15.0` | Sets the capture dwell time for each center-frequency chunk. Longer values give RDS more time to acquire PI/PS data but increase scan time. |
| `--output PATH` | Generated JSONL name | Selects the station-summary JSONL file. If omitted, the scanner creates `rds-scan-<resolved-sdr>-<bandwidth>Hz-<duration>s.jsonl`. The file is opened in append mode, so later scans add records rather than overwrite it. |
| `--center FREQ` | Full-band scan | Restricts the scan to one center frequency, such as `100M`. Without it, the configured FM band is divided into bandwidth-sized chunks. |
| `--band-start FREQ` | `88.1M` | Lower edge of the automatic full-band scan. Ignored for single-center scans. |
| `--band-end FREQ` | `107.9M` | Upper edge of the automatic full-band scan. Ignored for single-center scans. |
| `--spacing VALUE` | `200k` | FM channel spacing used to generate target frequencies. |
| `--targets LIST` | Automatic grid | Comma-separated target frequencies, for example `99.5M,100.3M,101.1M`. Valid only with `--center`; it overrides automatic channel generation. |
| `--cycles COUNT` | `0` | Number of full-band passes. `0` means continue indefinitely; `1` performs one pass. Single-center mode always performs one scan. |
| `--chunk-size BYTES` | `65536` | Read size for the `rx_sdr` pipe. Larger values can reduce read overhead; smaller values can improve responsiveness. |

## Gain and receiver process control

| Argument | Default | Effect |
| --- | --- | --- |
| `--rx-gain VALUE` | Profile/driver behavior | Uses one fixed gain for every chunk and bypasses automatic calibration. For profiles with disabled calibration, it overrides the profile default. |
| `--skip-gain-calibration` | Off | Prevents automatic per-chunk calibration when `--rx-gain` is not supplied. The receiver then uses its driver default gain. |
| `--force-gain-calibration` | Off | Repeats calibration even when a matching cached calibration file exists. Profiles that explicitly disable calibration reject this option. |
| `--gain-calibration-duration SECONDS` | `5.0` | Dwell time for each gain tested during calibration. Longer values improve scoring stability but extend startup time. |
| `--gain-calibration-incr DB` | Profile setting | Overrides the profile gain step during initial or forced calibration. Smaller steps test more gains; automatic profile steps are limited to no more than nine values per chunk. |
| `--gain-calibration-min-count COUNT` | `--min-pi-count` | Minimum PI detections before a PI/frequency pair contributes to gain calibration scoring. |
| `--gain-calibration-file PATH` | `rds_gain_calibration.json` | Stores per-chunk calibrated gains. Matching future scans reuse the cache unless forced to recalibrate. |
| `--rx-start-retries COUNT` | `3` | Number of attempts to start `rx_sdr` when it exits immediately. |
| `--rx-retry-delay SECONDS` | `1.0` | Delay between failed `rx_sdr` start attempts. Increase it for slow USB or network-backed receivers. |
| `--device-release-delay SECONDS` | `1.0` | Delay after a chunk before starting the next receiver process, allowing hardware and vendor services to release the device. |
| `--rx-arg VALUE` | None | Adds an advanced argument directly to `rx_sdr`. Repeat the option for multiple arguments; use profile options first whenever possible. |
| `--show-command` | Off | Prints generated `rx_sdr`, `csdr`, and `redsea` commands for pipeline debugging. |

## RDS and output behavior

| Argument | Default | Effect |
| --- | --- | --- |
| `--min-pi-count COUNT` | `3` | Minimum validated PI observations required before a station is written. Increasing it reduces false positives but can omit weak/intermittent stations. |
| `--freq-match-tolerance HZ` | `1000` | Maximum frequency difference allowed when matching a decoded station to the target grid. |
| `--no-echo` | Off | Suppresses confirmed PI messages on the console while continuing JSONL output. |
| `--pi-csv PATH` | `pi_codes_allocated.csv` | Local PI-code lookup CSV used to enrich station records. |
| `--pi-html PATH` | `pi_codes_allocated.html` | Cached downloaded PI-code source HTML. |
| `--pi-meta PATH` | `pi_codes_allocated.meta.json` | Metadata used to determine whether the cached PI-code source needs updating. |
| `--pi-url URL` | Project PI URL | Overrides the online PI-code source URL. |
| `--skip-pi-update` | Off | Uses local PI data without checking or downloading updates. |
| `--force-pi-update` | Off | Forces PI-code source download and CSV regeneration. |
| `--grid-base FREQ` | `88.1M` | Starting frequency for the automatic FM target grid. |

## RabbitEars uploads

Uploads are disabled unless `--tuner-key` is supplied.

| Argument | Default | Effect |
| --- | --- | --- |
| `--tuner-key KEY` | Disabled | Enables RabbitEars FM Live Band Scan uploads for the configured tuner. Keep credentials out of shell history and scripts where practical. |
| `--upload-debug` | Off | Prints each upload payload before compression. Use only for troubleshooting because output may be verbose. |
| `--upload-per-record-delay SECONDS` | `0.5` | Delay between individual station uploads. |
| `--upload-retries COUNT` | `3` | Number of retries for a failed upload. |
| `--upload-retry-delay SECONDS` | `5.0` | Delay between upload retries. |
| `--upload-timeout SECONDS` | `20` | Network timeout per upload request. |

## Profile inspection modes

These modes print information and exit without scanning:

```bash
fmbcb-rds-multi-scan --list-rx-sdr
fmbcb-rds-multi-scan --probe-rx-sdr
```

`--list-rx-sdr` shows configured profiles, gain behavior, and bandwidth rules.
`--probe-rx-sdr` shows detected SoapySDR devices and profile matches.

## Common examples

One full-band pass with the defaults for duration and output filename:

```bash
fmbcb-rds-multi-scan   --rx-sdr rtlsdr   --bandwidth 2.4M   --cycles 1
```

Single-center scan with an explicit output file and fixed gain:

```bash
fmbcb-rds-multi-scan   --rx-sdr sdrplay-rsp1a   --center 100M   --bandwidth 5M   --duration 20   --rx-gain 35   --output "$HOME/rds-scan-rsp1a-100M.jsonl"
```

Debug the generated pipeline without writing console station confirmations:

```bash
fmbcb-rds-multi-scan   --rx-sdr airspy-mini   --bandwidth 3M   --show-command   --no-echo
```

Run a short calibration with a custom retry delay:

```bash
fmbcb-rds-multi-scan   --rx-sdr rtlsdr   --bandwidth 2.4M   --gain-calibration-duration 3   --rx-retry-delay 2   --cycles 1
```

## File and restart behavior

Station summaries are written after each completed chunk or single-center scan.
The writer opens the selected path with append mode. This means rerunning the
same command preserves earlier JSONL records and appends new station summaries.
Use a new `--output` path when a clean survey dataset is required. Gain
calibration data is separate and is stored in `--gain-calibration-file`.
