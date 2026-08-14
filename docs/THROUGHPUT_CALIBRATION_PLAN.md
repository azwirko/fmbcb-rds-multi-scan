# Runtime Throughput Calibration Plan

This branch is for developing optional startup calibration that measures whether
the selected SDR, host, and complete `rx_sdr`/`csdr`/`redsea` pipeline can keep
up with a requested bandwidth. The stable `main` branch and tagged releases do
not enable this work by default.

## Branch workflow

Stable application work:

```bash
git switch main
git pull --ff-only origin main
git switch -c fix/short-description
```

Throughput-calibration work:

```bash
git switch feature/runtime-throughput-calibration
git pull --ff-only origin feature/runtime-throughput-calibration
```

Return to stable application behavior with:

```bash
git switch main
```

Do not merge this branch into `main` until calibration has been tested on
multiple SDRs, hosts, operating-system installations, and sample rates.

## Development steps

1. Capture `rx_sdr` stderr instead of discarding it and count the driver's `O`
   overrun indicators without blocking stdout consumption.
2. Add an explicit opt-in command-line mode such as
   `--run-throughput-calibration`; normal startup must remain unchanged.
3. Derive candidate bandwidths from the selected `RX_SDR_PROFILES` entry and
   test them from lower to higher rates.
4. Exercise the real pipeline for each candidate, including the actual number
   of `csdr` and `redsea` branches created for the bandwidth.
5. Record overrun count, process exits, broken pipes, elapsed time, CPU usage,
   load average, memory pressure, and per-process CPU usage.
6. Separate hardware-only testing from full-pipeline testing so USB/driver
   limits can be distinguished from downstream CPU backpressure.
7. Use conservative pass criteria: zero overruns, no unexpected exits, and
   sustained CPU utilization below a configurable safety threshold.
8. Select the highest passing bandwidth, apply a safety margin, and report the
   recommendation before any normal scan starts.
9. Add a short-lived or versioned cache keyed by SDR profile/model, bandwidth,
   CPU identity, native-tool versions, and pipeline settings.
10. Provide a fallback recommendation when no tested bandwidth passes, without
    silently changing the user's requested bandwidth.
11. Add focused tests for stderr overrun parsing, process cleanup, metric
    collection, pass/fail decisions, cache invalidation, and interruption.
12. Test explicitly with the hardware matrix documented in the stable README
    and record host CPU, connection type, firmware, bandwidth, branch count,
    overrun count, load, and decode results.

## Opt-in testing contract

Until this plan is complete, users should continue installing the tagged stable
release. Testers can switch to this branch in a disposable clone and invoke the
calibration option explicitly after it exists. The feature must never run merely
because a user installs from this branch, and it must not alter the selected
bandwidth or scan behavior without a clear diagnostic and explicit consent.

## Proposed result

```text
Runtime calibration:
  2.400 MHz: PASS, 0 overruns, CPU 48%, 13 pipelines
  3.200 MHz: PASS, 0 overruns, CPU 71%, 17 pipelines
  5.000 MHz: FAIL, 42 overruns, CPU 96%, 25 pipelines

Recommended maximum: 3.200 MHz
Safety margin: 10%
```
