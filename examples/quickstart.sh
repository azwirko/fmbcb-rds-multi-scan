#!/usr/bin/env bash
set -euo pipefail

# One-cycle RTL-SDR example. Adjust bandwidth/gain for your receiver.
fmbcb-rds-multi-scan \
  --rx-sdr rtlsdr \
  --bandwidth 2.4M \
  --duration 10 \
  --output "${HOME}/rds-scan.jsonl" \
  --cycles 1 \
  --show-command

# SDRplay example, assuming SDRplay API and SoapySDRPlay are installed:
# fmbcb-rds-multi-scan \
#   --rx-sdr sdrplay \
#   --bandwidth 5M \
#   --duration 10 \
#   --output "${HOME}/rds-scan.jsonl" \
#   --cycles 1
