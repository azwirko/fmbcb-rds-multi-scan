#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="fmbcb-rds-multi-scan"
PREFIX="${FMB_PREFIX:-/opt/${APP_NAME}}"
BIN_DIR="${FMB_BIN_DIR:-/usr/local/bin}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example: sudo ./uninstall.sh" >&2
  exit 1
fi

rm -f "${BIN_DIR}/${APP_NAME}" "${BIN_DIR}/fmbcb-rds-env-check"
rm -rf "$PREFIX"

echo "Removed ${APP_NAME} from ${PREFIX} and wrappers from ${BIN_DIR}."
echo "Native SDR tools and APT packages were left installed intentionally."
