#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="fmbcb-rds-multi-scan"
PREFIX="${FMB_PREFIX:-/opt/${APP_NAME}}"
BIN_DIR="${FMB_BIN_DIR:-/usr/local/bin}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

validate_install_path() {
  local name="$1"
  local value="$2"

  if [[ -z "$value" ]]; then
    die "${name} must not be empty."
  fi
  if [[ "$value" != /* ]]; then
    die "${name} must be an absolute path: ${value}"
  fi
  case "$value" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/usr/local|/var)
      die "${name} is too broad for uninstall writes/removal: ${value}"
      ;;
  esac
}

validate_install_path "FMB_PREFIX" "$PREFIX"
validate_install_path "FMB_BIN_DIR" "$BIN_DIR"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example: sudo ./uninstall.sh" >&2
  exit 1
fi

rm -f "${BIN_DIR}/${APP_NAME}" "${BIN_DIR}/fmbcb-rds-env-check"
rm -rf "$PREFIX"

echo "Removed ${APP_NAME} from ${PREFIX} and wrappers from ${BIN_DIR}."
echo "Native SDR tools and APT packages were left installed intentionally."
