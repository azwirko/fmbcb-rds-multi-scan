#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="fmbcb-rds-multi-scan"
DEFAULT_PREFIX="/opt/${APP_NAME}"
DEFAULT_BIN_DIR="/usr/local/bin"
DEFAULT_BUILD_ROOT="/usr/local/src/${APP_NAME}-deps"

PREFIX="${FMB_PREFIX:-$DEFAULT_PREFIX}"
BIN_DIR="${FMB_BIN_DIR:-$DEFAULT_BIN_DIR}"
BUILD_ROOT="${FMB_BUILD_ROOT:-$DEFAULT_BUILD_ROOT}"
FORCE_BUILD="${FMB_FORCE_BUILD:-0}"
SKIP_APT="${FMB_SKIP_APT:-0}"
SKIP_NATIVE_BUILD="${FMB_SKIP_NATIVE_BUILD:-0}"
SKIP_RX_SDR_BUILD="${FMB_SKIP_RX_SDR_BUILD:-0}"
SKIP_CSDR_BUILD="${FMB_SKIP_CSDR_BUILD:-0}"
SKIP_REDSEA_BUILD="${FMB_SKIP_REDSEA_BUILD:-0}"
INSTALL_RTL_BLACKLIST="${FMB_INSTALL_RTL_BLACKLIST:-0}"

RX_TOOLS_REPO="${FMB_RX_TOOLS_REPO:-https://github.com/xmikos/rx_tools.git}"
RX_TOOLS_REF="${FMB_RX_TOOLS_REF:-}"
CSDR_REPO="${FMB_CSDR_REPO:-https://github.com/ha7ilm/csdr.git}"
CSDR_REF="${FMB_CSDR_REF:-}"
REDSEA_REPO="${FMB_REDSEA_REPO:-https://github.com/windytan/redsea.git}"
REDSEA_REF="${FMB_REDSEA_REF:-}"

usage() {
  cat <<EOF
Usage: sudo ./install.sh [options]

Install ${APP_NAME}, create a Python virtual environment, install wrappers, and
build missing native SDR tools when needed.

Options:
  --prefix PATH              Install app under PATH [${DEFAULT_PREFIX}]
  --bin-dir PATH             Install command wrappers under PATH [${DEFAULT_BIN_DIR}]
  --build-root PATH          Native dependency source/build root [${DEFAULT_BUILD_ROOT}]
  --force-build              Rebuild native tools even when commands already exist
  --skip-apt                 Do not install APT packages
  --skip-native-build        Do not build rx_sdr, csdr, or redsea
  --skip-rx-sdr-build        Do not build rx_sdr
  --skip-csdr-build          Do not build csdr
  --skip-redsea-build        Do not build redsea
  --install-rtl-blacklist    Install a modprobe blacklist for DVB RTL modules
  -h, --help                 Show this help

Environment overrides:
  FMB_RX_TOOLS_REPO, FMB_RX_TOOLS_REF
  FMB_CSDR_REPO, FMB_CSDR_REF
  FMB_REDSEA_REPO, FMB_REDSEA_REF

Notes:
  SDRplay users still need the SDRplay API/SoapySDR module installed separately
  according to SDRplay's current Linux instructions.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --build-root) BUILD_ROOT="$2"; shift 2 ;;
    --force-build) FORCE_BUILD=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    --skip-native-build) SKIP_NATIVE_BUILD=1; shift ;;
    --skip-rx-sdr-build) SKIP_RX_SDR_BUILD=1; shift ;;
    --skip-csdr-build) SKIP_CSDR_BUILD=1; shift ;;
    --skip-redsea-build) SKIP_REDSEA_BUILD=1; shift ;;
    --install-rtl-blacklist) INSTALL_RTL_BLACKLIST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example: sudo ./install.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PREFIX}/venv"
APP_SRC_DIR="${PREFIX}/src"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

apt_install_available() {
  local requested=("$@")
  local installable=()
  local pkg
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  for pkg in "${requested[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      installable+=("$pkg")
    else
      warn "APT package not available on this release: $pkg"
    fi
  done
  if ((${#installable[@]})); then
    apt-get install -y --no-install-recommends "${installable[@]}"
  fi
}

clone_or_update() {
  local repo="$1"
  local ref="$2"
  local dest="$3"

  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" fetch --tags --prune
  else
    rm -rf "$dest"
    git clone "$repo" "$dest"
  fi

  if [[ -n "$ref" ]]; then
    git -C "$dest" checkout "$ref"
  fi
}

install_apt_deps() {
  [[ "$SKIP_APT" == "1" ]] && { warn "Skipping APT dependency install"; return; }

  log "Installing Debian/Ubuntu packages"
  apt_install_available \
    ca-certificates curl git build-essential make cmake pkg-config \
    python3 python3-venv python3-pip python3-dev \
    libusb-1.0-0-dev libfftw3-dev libsndfile1-dev libliquid-dev \
    meson ninja-build nlohmann-json3-dev \
    soapysdr-tools libsoapysdr-dev soapysdr-module-rtlsdr \
    rtl-sdr usbutils sox
}

build_rx_sdr() {
  [[ "$SKIP_NATIVE_BUILD" == "1" || "$SKIP_RX_SDR_BUILD" == "1" ]] && { warn "Skipping rx_sdr build"; return; }
  if have_cmd rx_sdr && [[ "$FORCE_BUILD" != "1" ]]; then
    log "rx_sdr already installed: $(command -v rx_sdr)"
    return
  fi

  log "Building rx_sdr"
  local src="${BUILD_ROOT}/rx_tools"
  clone_or_update "$RX_TOOLS_REPO" "$RX_TOOLS_REF" "$src"
  cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
  cmake --build "$src/build" --parallel "$(nproc)"
  cmake --install "$src/build"
  ldconfig || true
}

build_csdr() {
  [[ "$SKIP_NATIVE_BUILD" == "1" || "$SKIP_CSDR_BUILD" == "1" ]] && { warn "Skipping csdr build"; return; }
  if have_cmd csdr && [[ "$FORCE_BUILD" != "1" ]]; then
    log "csdr already installed: $(command -v csdr)"
    return
  fi

  log "Building csdr"
  local src="${BUILD_ROOT}/csdr"
  clone_or_update "$CSDR_REPO" "$CSDR_REF" "$src"
  make -C "$src" -j"$(nproc)"
  make -C "$src" install
  ldconfig || true
}

build_redsea() {
  [[ "$SKIP_NATIVE_BUILD" == "1" || "$SKIP_REDSEA_BUILD" == "1" ]] && { warn "Skipping redsea build"; return; }
  if have_cmd redsea && [[ "$FORCE_BUILD" != "1" ]]; then
    log "redsea already installed: $(command -v redsea)"
    return
  fi

  log "Building redsea"
  local src="${BUILD_ROOT}/redsea"
  clone_or_update "$REDSEA_REPO" "$REDSEA_REF" "$src"
  rm -rf "$src/build"
  meson setup "$src/build" "$src" --prefix=/usr/local
  meson compile -C "$src/build"
  meson install -C "$src/build"
  ldconfig || true
}

install_rtl_blacklist() {
  [[ "$INSTALL_RTL_BLACKLIST" == "1" ]] || return
  log "Installing RTL-SDR DVB module blacklist"
  cat > /etc/modprobe.d/blacklist-rtl-sdr.conf <<'EOF'
# Installed by fmbcb-rds-multi-scan installer.
# Prevent Linux DVB drivers from claiming RTL-SDR receivers.
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
  warn "Reboot or unplug/replug the RTL-SDR device after blacklisting modules."
}

install_python_app() {
  log "Installing ${APP_NAME} into ${PREFIX}"
  mkdir -p "$PREFIX" "$BIN_DIR"
  rm -rf "$APP_SRC_DIR"
  mkdir -p "$APP_SRC_DIR"

  # Copy the repository snapshot used for installation. Exclude git/build cache.
  tar -C "$REPO_ROOT" \
    --exclude='.git' \
    --exclude='*.tar.gz' \
    --exclude='build' \
    --exclude='dist' \
    -cf - . | tar -C "$APP_SRC_DIR" -xf -

  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install "$APP_SRC_DIR"
}

install_wrappers() {
  log "Installing command wrappers in ${BIN_DIR}"
  cat > "${BIN_DIR}/${APP_NAME}" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/${APP_NAME}" "\$@"
EOF
  cat > "${BIN_DIR}/fmbcb-rds-env-check" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/fmbcb-rds-env-check" "\$@"
EOF
  chmod 0755 "${BIN_DIR}/${APP_NAME}" "${BIN_DIR}/fmbcb-rds-env-check"
}

main() {
  install_apt_deps
  mkdir -p "$BUILD_ROOT"
  build_rx_sdr
  build_csdr
  build_redsea
  install_rtl_blacklist
  install_python_app
  install_wrappers

  log "Running environment checker"
  if ! "${BIN_DIR}/fmbcb-rds-env-check"; then
    warn "Install completed, but the environment checker reported problems. Review the messages above."
  fi

  cat <<EOF

Install complete.

Try:
  ${APP_NAME} --help
  fmbcb-rds-env-check

Example full-band scan:
  ${APP_NAME} --rx-sdr rtlsdr --bandwidth 2.4M --duration 10 --output ~/rds-scan.jsonl --cycles 1
EOF
}

main "$@"
