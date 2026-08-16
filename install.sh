#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="fmbcb-rds-multi-scan"
DEFAULT_PREFIX="/opt/${APP_NAME}"
DEFAULT_BIN_DIR="/usr/local/bin"
DEFAULT_CONFIG_DIR="/etc/${APP_NAME}"
DEFAULT_BUILD_ROOT="/usr/local/src/${APP_NAME}-deps"

PREFIX="${FMB_PREFIX:-$DEFAULT_PREFIX}"
BIN_DIR="${FMB_BIN_DIR:-$DEFAULT_BIN_DIR}"
CONFIG_DIR="${FMB_CONFIG_DIR:-$DEFAULT_CONFIG_DIR}"
BUILD_ROOT="${FMB_BUILD_ROOT:-$DEFAULT_BUILD_ROOT}"
FORCE_BUILD="${FMB_FORCE_BUILD:-0}"
SKIP_APT="${FMB_SKIP_APT:-0}"
SKIP_NATIVE_BUILD="${FMB_SKIP_NATIVE_BUILD:-0}"
SKIP_RX_SDR_BUILD="${FMB_SKIP_RX_SDR_BUILD:-0}"
SKIP_CSDR_BUILD="${FMB_SKIP_CSDR_BUILD:-0}"
SKIP_REDSEA_BUILD="${FMB_SKIP_REDSEA_BUILD:-0}"
INSTALL_RTL_BLACKLIST="${FMB_INSTALL_RTL_BLACKLIST:-0}"
DRY_RUN="${FMB_DRY_RUN:-0}"

RX_TOOLS_REPO="${FMB_RX_TOOLS_REPO:-https://github.com/rxseger/rx_tools}"
RX_TOOLS_REF="${FMB_RX_TOOLS_REF:-}"
CSDR_REPO="${FMB_CSDR_REPO:-https://github.com/ha7ilm/csdr.git}"
CSDR_REF="${FMB_CSDR_REF:-}"
REDSEA_REPO="${FMB_REDSEA_REPO:-https://github.com/windytan/redsea.git}"
REDSEA_REF="${FMB_REDSEA_REF:-}"
SDRPLAY_API_URL="${FMB_SDRPLAY_API_URL:-https://www.sdrplay.com/software/SDRplay_RSP_API-Linux-3.15.2.run}"
SDRPLAY_API_INSTALLER_OVERRIDE="${FMB_SDRPLAY_API_INSTALLER:-}"
SDRPLAY_API_SERVICE="${FMB_SDRPLAY_API_SERVICE:-sdrplay}"
SOAPY_SDRPLAY_REPO="${FMB_SOAPY_SDRPLAY_REPO:-https://github.com/pothosware/SoapySDRPlay3.git}"
SOAPY_SDRPLAY_REF="${FMB_SOAPY_SDRPLAY_REF:-}"
SOAPY_AIRSPYHF_REPO="${FMB_SOAPY_AIRSPYHF_REPO:-https://github.com/pothosware/SoapyAirspyHF.git}"
SOAPY_AIRSPYHF_REF="${FMB_SOAPY_AIRSPYHF_REF:-}"
SOAPY_PLUTOSDR_REPO="${FMB_SOAPY_PLUTOSDR_REPO:-https://github.com/pothosware/SoapyPlutoSDR.git}"
SOAPY_PLUTOSDR_REF="${FMB_SOAPY_PLUTOSDR_REF:-}"
SOAPY_FCDPP_REPO="${FMB_SOAPY_FCDPP_REPO:-https://github.com/pothosware/SoapyFCDPP.git}"
SOAPY_FCDPP_REF="${FMB_SOAPY_FCDPP_REF:-}"
SKIP_SDRPLAY="${FMB_SKIP_SDRPLAY:-0}"
SKIP_SOAPY_EXTRA_BUILD="${FMB_SKIP_SOAPY_EXTRA_BUILD:-0}"
SKIP_SDRPLAY_API="${FMB_SKIP_SDRPLAY_API:-0}"
SKIP_SOAPY_SDRPLAY_BUILD="${FMB_SKIP_SOAPY_SDRPLAY_BUILD:-0}"
SKIP_BUILD_PREREQ_APT="${FMB_SKIP_BUILD_PREREQ_APT:-0}"
APT_UPDATED=0

usage() {
  cat <<EOF
Usage: sudo ./install.sh [options]

Install ${APP_NAME}, create a Python virtual environment, install wrappers, and
build missing native SDR tools when needed. Distro SoapySDR tools, development
files, and module bundle are installed through APT. SDRplay API 3.x,
SoapySDRPlay3, SoapyAirspyHF, SoapyPlutoSDR, and SoapyFCDPP are checked and
installed or built when missing.

Options:
  --prefix PATH              Install app under PATH [${DEFAULT_PREFIX}]
  --bin-dir PATH             Install command wrappers under PATH [${DEFAULT_BIN_DIR}]
  --config-dir PATH          Install editable app config under PATH [${DEFAULT_CONFIG_DIR}]
  --build-root PATH          Native dependency source/build root [${DEFAULT_BUILD_ROOT}]
  --force-build              Rebuild native tools even when commands already exist
  --skip-apt                 Do not install the full runtime APT package group
  --skip-native-build        Do not build rx_sdr, csdr, or redsea
  --skip-rx-sdr-build        Do not build rx_sdr
  --skip-csdr-build          Do not build csdr
  --skip-redsea-build        Do not build redsea
  --skip-sdrplay             Do not install SDRplay API or SoapySDRPlay3
  --skip-sdrplay-api         Do not install/start the SDRplay API service
  --skip-soapy-sdrplay-build Do not build SoapySDRPlay3 from source
  --skip-soapy-extra-build  Do not build AirspyHF, PlutoSDR, or FCDPP modules
  --skip-build-prereq-apt   Do not auto-install source-build prerequisites
  --install-rtl-blacklist    Install a modprobe blacklist for DVB RTL modules
  --dry-run, --check         Validate options and print the install plan
  -h, --help                 Show this help

Environment overrides:
  FMB_CONFIG_DIR
  FMB_RX_TOOLS_REPO, FMB_RX_TOOLS_REF
  FMB_CSDR_REPO, FMB_CSDR_REF
  FMB_REDSEA_REPO, FMB_REDSEA_REF
  FMB_SDRPLAY_API_URL, FMB_SDRPLAY_API_INSTALLER, FMB_SDRPLAY_API_SERVICE
  FMB_SOAPY_SDRPLAY_REPO, FMB_SOAPY_SDRPLAY_REF
  FMB_SOAPY_AIRSPYHF_REPO, FMB_SOAPY_AIRSPYHF_REF
  FMB_SOAPY_PLUTOSDR_REPO, FMB_SOAPY_PLUTOSDR_REF
  FMB_SOAPY_FCDPP_REPO, FMB_SOAPY_FCDPP_REF
  FMB_SKIP_SOAPY_EXTRA_BUILD, FMB_SKIP_BUILD_PREREQ_APT

Notes:
  The SDRplay API vendor installer may prompt for EULA acceptance. Press Y only
  if you accept SDRplay's license terms.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_option_value() {
  local option="$1"
  local value="${2-}"
  if [[ -z "$value" || "$value" == -* ]]; then
    echo "Missing value for ${option}" >&2
    usage >&2
    exit 2
  fi
}

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
      die "${name} is too broad for installer writes/removal: ${value}"
      ;;
  esac
}

check_debian_compliance() {
  [[ -r /etc/os-release ]] || die "Cannot identify the operating system: /etc/os-release is missing."

  # shellcheck disable=SC1091
  . /etc/os-release
  local distro_id="${ID:-}"
  local distro_like="${ID_LIKE:-}"

  case " ${distro_id} ${distro_like} " in
    *" debian "*|*" ubuntu "*) ;;
    *)
      die "Unsupported operating system '${distro_id:-unknown}'. This installer requires Debian or Ubuntu, or a Debian-compatible derivative."
      ;;
  esac

  local required_cmd
  for required_cmd in apt-get apt-cache dpkg; do
    command -v "$required_cmd" >/dev/null 2>&1 || die "Debian package tool not found: ${required_cmd}."
  done

  OS_ID="$distro_id"
  OS_VERSION_ID="${VERSION_ID:-unknown}"
  OS_ID_LIKE="$distro_like"
}

validate_install_paths() {
  validate_install_path "--prefix/FMB_PREFIX" "$PREFIX"
  validate_install_path "--bin-dir/FMB_BIN_DIR" "$BIN_DIR"
  validate_install_path "--config-dir/FMB_CONFIG_DIR" "$CONFIG_DIR"
  validate_install_path "--build-root/FMB_BUILD_ROOT" "$BUILD_ROOT"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) require_option_value "$1" "${2-}"; PREFIX="$2"; shift 2 ;;
    --bin-dir) require_option_value "$1" "${2-}"; BIN_DIR="$2"; shift 2 ;;
    --config-dir) require_option_value "$1" "${2-}"; CONFIG_DIR="$2"; shift 2 ;;
    --build-root) require_option_value "$1" "${2-}"; BUILD_ROOT="$2"; shift 2 ;;
    --force-build) FORCE_BUILD=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    --skip-native-build) SKIP_NATIVE_BUILD=1; shift ;;
    --skip-rx-sdr-build) SKIP_RX_SDR_BUILD=1; shift ;;
    --skip-csdr-build) SKIP_CSDR_BUILD=1; shift ;;
    --skip-redsea-build) SKIP_REDSEA_BUILD=1; shift ;;
    --skip-sdrplay) SKIP_SDRPLAY=1; shift ;;
    --skip-sdrplay-api) SKIP_SDRPLAY_API=1; shift ;;
    --skip-soapy-sdrplay-build) SKIP_SOAPY_SDRPLAY_BUILD=1; shift ;;
    --skip-soapy-extra-build) SKIP_SOAPY_EXTRA_BUILD=1; shift ;;
    --skip-build-prereq-apt) SKIP_BUILD_PREREQ_APT=1; shift ;;
    --install-rtl-blacklist) INSTALL_RTL_BLACKLIST=1; shift ;;
    --dry-run|--check) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

check_debian_compliance
validate_install_paths

SDRPLAY_API_INSTALLER="${SDRPLAY_API_INSTALLER_OVERRIDE:-${BUILD_ROOT}/downloads/SDRplay_RSP_API-Linux-3.15.2.run}"
if [[ "$SDRPLAY_API_INSTALLER" != /* ]]; then
  die "FMB_SDRPLAY_API_INSTALLER must be an absolute path: ${SDRPLAY_API_INSTALLER}"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PREFIX}/venv"
APP_SRC_DIR="${PREFIX}/src"
INSTALL_INFO_FILE="${PREFIX}/install-info.env"
RX_SDR_PROFILE_CONFIG_FILE="${CONFIG_DIR}/rx_sdr_profiles.json"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }
require_cmd() { have_cmd "$1" || die "Required command not found: $1"; }

APT_REQUIRED_PACKAGES=(
  ca-certificates curl git build-essential make cmake pkg-config
  software-properties-common
  python3 python3-venv python3-pip python3-dev
  libusb-1.0-0-dev libfftw3-dev libsndfile1-dev libliquid-dev
  libairspyhf-dev libiio-dev libad9361-dev libhidapi-dev libasound2-dev
  limesuite limesuite-udev liblimesuite-dev
  meson ninja-build nlohmann-json3-dev
  soapysdr-tools libsoapysdr-dev soapysdr-module-all usbutils
)

APT_OPTIONAL_PACKAGES=()

APT_BUILD_PREREQ_PACKAGES=(
  ca-certificates curl git build-essential make cmake pkg-config
  software-properties-common
  libusb-1.0-0-dev libfftw3-dev libsndfile1-dev libliquid-dev
  libairspyhf-dev libiio-dev libad9361-dev libhidapi-dev libasound2-dev
  limesuite limesuite-udev liblimesuite-dev
  meson ninja-build nlohmann-json3-dev libsoapysdr-dev soapysdr-tools
)

git_output() {
  local repo_dir="$1"
  shift
  git -C "$repo_dir" "$@" 2>/dev/null || true
}

git_commit_for_dir() {
  local repo_dir="$1"
  [[ -d "$repo_dir/.git" ]] || return 0
  git_output "$repo_dir" rev-parse HEAD
}

git_branch_for_dir() {
  local repo_dir="$1"
  [[ -d "$repo_dir/.git" ]] || return 0
  git_output "$repo_dir" branch --show-current
}

git_dirty_for_dir() {
  local repo_dir="$1"
  [[ -d "$repo_dir/.git" ]] || { printf 'unknown\n'; return 0; }
  if [[ -n "$(git_output "$repo_dir" status --porcelain)" ]]; then
    printf 'yes\n'
  else
    printf 'no\n'
  fi
}

write_env_kv() {
  local key="$1"
  local value="${2-}"
  printf '%s=%q\n' "$key" "$value" >> "$INSTALL_INFO_FILE"
}

enable_ubuntu_universe() {
  [[ -r /etc/os-release ]] || return 0
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || return 0

  if ! have_cmd add-apt-repository; then
    apt_update_once
    apt-get install -y --no-install-recommends software-properties-common
  fi

  if add-apt-repository -y universe >/dev/null 2>&1; then
    APT_UPDATED=0
  fi
}

apt_package_available() {
  apt-cache show "$1" >/dev/null 2>&1
}

apt_package_installed() {
  dpkg-query -W -f='${db:Status-Abbrev}' "$1" 2>/dev/null | grep -q '^ii '
}

apt_update_once() {
  if [[ "$APT_UPDATED" == "0" ]]; then
    log "Updating APT package metadata"
    apt-get update
    APT_UPDATED=1
  fi
}

print_package_list() {
  local label="$1"
  shift
  local pkg
  printf '  %s:\n' "$label"
  for pkg in "$@"; do
    printf '    - %s\n' "$pkg"
  done
}

print_native_plan() {
  local command_name="$1"
  local skip_flag="$2"
  local repo="$3"
  local ref="$4"
  local dest="$5"

  printf '  %s:\n' "$command_name"
  if [[ "$SKIP_NATIVE_BUILD" == "1" || "$skip_flag" == "1" ]]; then
    printf '    action: skip build\n'
    return
  fi
  if have_cmd "$command_name" && [[ "$FORCE_BUILD" != "1" ]]; then
    printf '    action: use existing command\n'
    printf '    command: %s\n' "$(command -v "$command_name")"
    return
  fi
  printf '    action: build from source\n'
  printf '    repo: %s\n' "$repo"
  printf '    ref: %s\n' "${ref:-remote default branch}"
  printf '    source: %s\n' "$dest"
}

print_sdrplay_plan() {
  printf '  SDRplay API service:\n'
  if [[ "$SKIP_SDRPLAY" == "1" || "$SKIP_SDRPLAY_API" == "1" ]]; then
    printf '    action: skip API installer and service management\n'
  else
    printf '    action: check service, download/run API installer if missing, enable/start service\n'
    printf '    service: %s\n' "$SDRPLAY_API_SERVICE"
    printf '    installer URL: %s\n' "$SDRPLAY_API_URL"
    printf '    installer path: %s\n' "$SDRPLAY_API_INSTALLER"
  fi

  printf '  SoapySDRPlay3:\n'
  if [[ "$SKIP_SDRPLAY" == "1" || "$SKIP_SOAPY_SDRPLAY_BUILD" == "1" ]]; then
    printf '    action: skip SoapySDRPlay3 source build\n'
  else
    printf '    action: check loaded SoapySDR module, build from source if missing\n'
    printf '    repo: %s\n' "$SOAPY_SDRPLAY_REPO"
    printf '    ref: %s\n' "${SOAPY_SDRPLAY_REF:-remote default branch}"
    printf '    source: %s\n' "${BUILD_ROOT}/SoapySDRPlay3"
  fi
}

print_soapy_extra_plan() {
  printf '  SoapyAirspyHF:      %s\n' "$SOAPY_AIRSPYHF_REPO"
  printf '  SoapyPlutoSDR:      %s\n' "$SOAPY_PLUTOSDR_REPO"
  printf '  SoapyFCDPP:         %s\n' "$SOAPY_FCDPP_REPO"
  if [[ "$SKIP_SOAPY_EXTRA_BUILD" == "1" ]]; then
    printf '    action: skip extra SoapySDR module source builds\n'
  else
    printf '    action: check loaded modules, build each missing module from source\n'
  fi
}

print_dry_run() {
  cat <<EOF
${APP_NAME} install preflight

Platform:
  operating system: ${OS_ID} ${OS_VERSION_ID}
  Debian family:    ${OS_ID_LIKE:-none reported}

Paths:
  repo root:      ${REPO_ROOT}
  prefix:         ${PREFIX}
  bin dir:        ${BIN_DIR}
  build root:     ${BUILD_ROOT}
  config dir:     ${CONFIG_DIR}
  profile config: ${RX_SDR_PROFILE_CONFIG_FILE}
  venv:           ${VENV_DIR}
  app source:     ${APP_SRC_DIR}
  install info:   ${INSTALL_INFO_FILE}

Toggles:
  skip apt:             ${SKIP_APT}
  skip native build:    ${SKIP_NATIVE_BUILD}
  force build:          ${FORCE_BUILD}
  install RTL blacklist: ${INSTALL_RTL_BLACKLIST}
  skip SDRplay:         ${SKIP_SDRPLAY}
  skip SDRplay API:     ${SKIP_SDRPLAY_API}
  skip SoapySDRPlay3:   ${SKIP_SOAPY_SDRPLAY_BUILD}
  skip extra Soapy modules: ${SKIP_SOAPY_EXTRA_BUILD}
  skip build prereq APT: ${SKIP_BUILD_PREREQ_APT}

APT:
EOF

  if [[ "$SKIP_APT" == "1" ]]; then
    printf '  action: skip full APT package install\n'
  else
    print_package_list "required packages" "${APT_REQUIRED_PACKAGES[@]}"
    if ((${#APT_OPTIONAL_PACKAGES[@]})); then
      print_package_list "optional packages" "${APT_OPTIONAL_PACKAGES[@]}"
    fi
  fi

  cat <<EOF

Native tools:
EOF
  print_native_plan "rx_sdr" "$SKIP_RX_SDR_BUILD" "$RX_TOOLS_REPO" "$RX_TOOLS_REF" "${BUILD_ROOT}/rx_tools"
  print_native_plan "csdr" "$SKIP_CSDR_BUILD" "$CSDR_REPO" "$CSDR_REF" "${BUILD_ROOT}/csdr"
  print_native_plan "redsea" "$SKIP_REDSEA_BUILD" "$REDSEA_REPO" "$REDSEA_REF" "${BUILD_ROOT}/redsea"

  cat <<EOF

SDRplay support:
EOF
  print_sdrplay_plan
  print_soapy_extra_plan

  cat <<EOF

Python app:
  action: create/update virtual environment and install curated source snapshot
  config: seed ${RX_SDR_PROFILE_CONFIG_FILE} if missing
  wrappers:
    - ${BIN_DIR}/${APP_NAME}
    - ${BIN_DIR}/fmbcb-rds-env-check

No changes were made. Run without --dry-run/--check as root to install.
EOF
}

apt_install_required() {
  local requested=("$@")
  local missing=()
  local pkg
  for pkg in "${requested[@]}"; do
    if ! apt_package_available "$pkg"; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]})); then
    printf 'ERROR: Required APT package(s) are not available on this release:\n' >&2
    printf '  %s\n' "${missing[@]}" >&2
    printf 'Review docs/INSTALL.md or rerun with --skip-apt only if these are installed another way.\n' >&2
    exit 1
  fi
  apt-get install -y --no-install-recommends "${requested[@]}"
}

apt_install_optional() {
  local requested=("$@")
  local installable=()
  local pkg
  for pkg in "${requested[@]}"; do
    if apt_package_available "$pkg"; then
      installable+=("$pkg")
    else
      warn "Optional APT package not available on this release: $pkg"
    fi
  done
  if ((${#installable[@]})); then
    apt-get install -y --no-install-recommends "${installable[@]}"
  fi
}

install_missing_apt_packages() {
  local reason="$1"
  shift
  local requested=("$@")
  local missing=()
  local pkg

  enable_ubuntu_universe
  for pkg in "${requested[@]}"; do
    if ! apt_package_available "$pkg"; then
      missing+=("$pkg")
    elif ! apt_package_installed "$pkg"; then
      missing+=("$pkg")
    fi
  done

  if ((${#missing[@]} == 0)); then
    return
  fi

  if [[ "$SKIP_BUILD_PREREQ_APT" == "1" ]]; then
    printf 'ERROR: Missing APT package(s) required for %s:\n' "$reason" >&2
    printf '  %s\n' "${missing[@]}" >&2
    printf 'Rerun without --skip-build-prereq-apt or install these packages manually.\n' >&2
    exit 1
  fi

  log "Installing Debian/Ubuntu packages required for ${reason}"
  apt_update_once
  apt-get install -y --no-install-recommends "${missing[@]}"
}

ensure_source_build_prereqs() {
  local reason="$1"
  shift
  install_missing_apt_packages "$reason" "${APT_BUILD_PREREQ_PACKAGES[@]}" "$@"
}

clone_or_update() {
  local repo="$1"
  local ref="$2"
  local dest="$3"

  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" remote set-url origin "$repo"
    git -C "$dest" fetch --tags --prune
  elif [[ -e "$dest" ]]; then
    if [[ "$FORCE_BUILD" == "1" ]]; then
      rm -rf "$dest"
      git clone "$repo" "$dest"
    else
      die "Build source path exists but is not a git checkout: $dest. Remove it or rerun with --force-build."
    fi
  else
    git clone "$repo" "$dest"
  fi

  if [[ -n "$ref" ]]; then
    git -C "$dest" checkout --detach "$ref"
  else
    git -C "$dest" remote set-head origin --auto >/dev/null 2>&1 || true
    local remote_head
    remote_head="$(git -C "$dest" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    if [[ -n "$remote_head" ]]; then
      git -C "$dest" checkout --detach "$remote_head"
    else
      warn "Could not determine default branch for $repo; leaving current checkout in place."
    fi
  fi

  log "Using $(basename "$dest") commit $(git -C "$dest" rev-parse --short HEAD)"
}

install_apt_deps() {
  [[ "$SKIP_APT" == "1" ]] && { warn "Skipping APT dependency install"; return; }

  export DEBIAN_FRONTEND=noninteractive
  apt_update_once
  enable_ubuntu_universe
  apt_update_once

  log "Installing required Debian/Ubuntu packages"
  apt_install_required "${APT_REQUIRED_PACKAGES[@]}"

  if ((${#APT_OPTIONAL_PACKAGES[@]})); then
    log "Installing optional Debian/Ubuntu packages when available"
    apt_install_optional "${APT_OPTIONAL_PACKAGES[@]}"
  fi
}

reload_limesdr_udev_rules() {
  have_cmd udevadm || { warn "udevadm is not installed; cannot reload LimeSDR rules"; return; }
  log "Reloading LimeSDR udev rules"
  udevadm control --reload-rules
  udevadm trigger
}

sdrplay_service_unit_exists() {
  systemctl list-unit-files "${SDRPLAY_API_SERVICE}.service" --no-legend 2>/dev/null | grep -Fq "${SDRPLAY_API_SERVICE}.service"
}

sdrplay_service_active() {
  systemctl is-active --quiet "$SDRPLAY_API_SERVICE"
}

soapy_sdrplay_module_loaded() {
  have_cmd SoapySDRUtil || return 1
  # Do not use grep -q with pipefail: SoapySDRUtil can receive SIGPIPE
  # after grep finds an early match and make a successful probe look failed.
  SoapySDRUtil --info 2>&1 | grep -Ei 'sdrplay|sdrPlay|SoapySDRPlay' >/dev/null
}

install_sdrplay_api() {
  [[ "$SKIP_SDRPLAY" == "1" || "$SKIP_SDRPLAY_API" == "1" ]] && { warn "Skipping SDRplay API install/service check"; return; }

  install_missing_apt_packages "SDRplay API download" ca-certificates curl
  require_cmd curl
  require_cmd systemctl

  if sdrplay_service_active; then
    log "SDRplay API service already active: ${SDRPLAY_API_SERVICE}"
    return
  fi

  if sdrplay_service_unit_exists; then
    log "Enabling and starting existing SDRplay API service: ${SDRPLAY_API_SERVICE}"
    systemctl enable "$SDRPLAY_API_SERVICE"
    systemctl start "$SDRPLAY_API_SERVICE"
  else
    log "Downloading SDRplay API installer"
    mkdir -p "$(dirname "$SDRPLAY_API_INSTALLER")"
    curl -fL --retry 3 -o "$SDRPLAY_API_INSTALLER" "$SDRPLAY_API_URL"
    chmod 0755 "$SDRPLAY_API_INSTALLER"

    warn "The SDRplay API installer may prompt for EULA acceptance. Press Y only if you accept SDRplay's license terms."
    "$SDRPLAY_API_INSTALLER"

    systemctl daemon-reload || true
    systemctl enable "$SDRPLAY_API_SERVICE"
    systemctl start "$SDRPLAY_API_SERVICE"
  fi

  if ! sdrplay_service_active; then
    die "SDRplay API service is not active after install/start: ${SDRPLAY_API_SERVICE}"
  fi
}

build_soapy_sdrplay() {
  [[ "$SKIP_SDRPLAY" == "1" || "$SKIP_SOAPY_SDRPLAY_BUILD" == "1" ]] && { warn "Skipping SoapySDRPlay3 build"; return; }

  if soapy_sdrplay_module_loaded && [[ "$FORCE_BUILD" != "1" ]]; then
    log "SoapySDRPlay3 module already loaded by SoapySDR"
    return
  fi

  ensure_source_build_prereqs "SoapySDRPlay3 source build"
  require_cmd SoapySDRUtil
  require_cmd git
  require_cmd cmake

  log "Building SoapySDRPlay3"
  local src="${BUILD_ROOT}/SoapySDRPlay3"
  clone_or_update "$SOAPY_SDRPLAY_REPO" "$SOAPY_SDRPLAY_REF" "$src"
  cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
  cmake --build "$src/build" --parallel "$(nproc)"
  cmake --install "$src/build"
  ldconfig || true

  if ! soapy_sdrplay_module_loaded; then
    die "SoapySDRPlay3 installed, but SoapySDRUtil --info does not show an SDRplay module."
  fi
}

install_sdrplay_support() {
  [[ "$SKIP_SDRPLAY" == "1" ]] && { warn "Skipping SDRplay support install/check"; return; }

  install_sdrplay_api
  build_soapy_sdrplay
}

soapy_module_loaded() {
  local module_name="$1"
  have_cmd SoapySDRUtil || return 1
  # Consume all output so pipefail does not turn grep's early exit into SIGPIPE.
  SoapySDRUtil --info 2>&1 | grep -Ei "${module_name}" >/dev/null
}

build_soapy_module() {
  local display_name="$1"
  local module_name="$2"
  local repo="$3"
  local ref="$4"
  local source_dir="$5"

  if soapy_module_loaded "$module_name" && [[ "$FORCE_BUILD" != "1" ]]; then
    log "${display_name} module already loaded by SoapySDR"
    return
  fi

  ensure_source_build_prereqs "${display_name} source build"
  require_cmd SoapySDRUtil
  require_cmd git
  require_cmd cmake

  log "Building ${display_name}"
  clone_or_update "$repo" "$ref" "$source_dir"
  cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
  cmake --build "$source_dir/build" --parallel "$(nproc)"
  cmake --install "$source_dir/build"
  ldconfig || true

  if ! soapy_module_loaded "$module_name"; then
    die "${display_name} installed, but SoapySDRUtil --info does not show module '${module_name}'."
  fi
}

build_soapy_extra_modules() {
  [[ "$SKIP_SOAPY_EXTRA_BUILD" == "1" ]] && { warn "Skipping extra SoapySDR module builds"; return; }

  build_soapy_module "SoapyAirspyHF" "airspyhf" "$SOAPY_AIRSPYHF_REPO" "$SOAPY_AIRSPYHF_REF" "${BUILD_ROOT}/SoapyAirspyHF"
  build_soapy_module "SoapyPlutoSDR" "plutosdr" "$SOAPY_PLUTOSDR_REPO" "$SOAPY_PLUTOSDR_REF" "${BUILD_ROOT}/SoapyPlutoSDR"
  build_soapy_module "SoapyFCDPP" "fcdpp" "$SOAPY_FCDPP_REPO" "$SOAPY_FCDPP_REF" "${BUILD_ROOT}/SoapyFCDPP"
}

print_soapy_support() {
  if ! have_cmd SoapySDRUtil; then
    warn "SoapySDRUtil is not installed; cannot print loaded SDR module support."
    return
  fi

  log "Loaded SoapySDR module support"
  SoapySDRUtil --info || warn "SoapySDRUtil --info failed."
  local module_name
  for module_name in airspyhf plutosdr fcdpp lime; do
    if soapy_module_loaded "$module_name"; then
      log "SoapySDR module loaded: ${module_name}"
    else
      warn "SoapySDR module not reported by SoapySDRUtil: ${module_name}"
    fi
  done

  log "Detected SoapySDR devices"
  SoapySDRUtil --find || warn "SoapySDRUtil --find did not detect devices."

  log "SDRplay SoapySDR check"
  SoapySDRUtil --find=sdrplay || warn "SoapySDRUtil --find=sdrplay did not detect an SDRplay device. Connect hardware and confirm ${SDRPLAY_API_SERVICE} is active."

  log "SDRplay SoapySDR probe"
  SoapySDRUtil --probe="driver=sdrplay" || warn "SoapySDRUtil --probe=driver=sdrplay failed. This can happen when no SDRplay receiver is attached."
}

build_rx_sdr() {
  [[ "$SKIP_NATIVE_BUILD" == "1" || "$SKIP_RX_SDR_BUILD" == "1" ]] && { warn "Skipping rx_sdr build"; return; }
  if have_cmd rx_sdr && [[ "$FORCE_BUILD" != "1" ]]; then
    log "rx_sdr already installed: $(command -v rx_sdr)"
    return
  fi

  ensure_source_build_prereqs "rx_sdr source build"
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

  ensure_source_build_prereqs "csdr source build"
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

  ensure_source_build_prereqs "redsea source build"
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
  [[ "$INSTALL_RTL_BLACKLIST" == "1" ]] || return 0
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

install_rx_sdr_profile_config() {
  log "Installing editable rx_sdr profile config"
  mkdir -p "$CONFIG_DIR"

  if [[ -f "$RX_SDR_PROFILE_CONFIG_FILE" ]]; then
    warn "Keeping existing rx_sdr profile values and adding any new default profiles: ${RX_SDR_PROFILE_CONFIG_FILE}"
    local merged_config
    merged_config="${RX_SDR_PROFILE_CONFIG_FILE}.tmp.$$"
    if ! python3 - "$RX_SDR_PROFILE_CONFIG_FILE" "$REPO_ROOT/config/rx_sdr_profiles.json" "$merged_config" <<'PYMERGE'
import json
import os
import sys

existing_path, defaults_path, output_path = sys.argv[1:]
with open(existing_path, encoding="utf-8") as stream:
    existing = json.load(stream)
with open(defaults_path, encoding="utf-8") as stream:
    defaults = json.load(stream)

existing_profiles = existing.setdefault("profiles", {})
default_profiles = defaults.get("profiles", {})
for name, profile in default_profiles.items():
    if name not in existing_profiles:
        existing_profiles[name] = profile
        continue

    # Migrate profiles from the former sample_rate-list schema while preserving
    # all other user edits. New defaults are authoritative only for the new
    # bandwidth schema, which is required by the installed scanner.
    existing_profile = existing_profiles[name]
    if "bandwidth" not in existing_profile and "bandwidth" in profile:
        existing_profile["bandwidth"] = profile["bandwidth"]
    existing_profile.pop("sample_rate", None)

existing_aliases = existing.setdefault("aliases", {})
for name, targets in defaults.get("aliases", {}).items():
    if name not in existing_aliases:
        existing_aliases[name] = targets
    elif isinstance(existing_aliases[name], list):
        for target in targets:
            if target not in existing_aliases[name]:
                existing_aliases[name].append(target)

with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(existing, stream, indent=2)
    stream.write("\n")
os.chmod(output_path, 0o644)
PYMERGE
    then
      install -m 0644 "$merged_config" "$RX_SDR_PROFILE_CONFIG_FILE"
      rm -f "$merged_config"
    else
      rm -f "$merged_config"
      die "Could not merge default rx_sdr profiles into ${RX_SDR_PROFILE_CONFIG_FILE}."
    fi
    return
  fi

  install -m 0644 "$REPO_ROOT/config/rx_sdr_profiles.json" "$RX_SDR_PROFILE_CONFIG_FILE"
}

install_python_app() {
  log "Installing ${APP_NAME} into ${PREFIX}"
  mkdir -p "$PREFIX" "$BIN_DIR"
  rm -rf "$APP_SRC_DIR"
  mkdir -p "$APP_SRC_DIR"

  # Copy only files needed for install, docs, and examples. Keep local runtime
  # data, editor files, secrets, and VCS metadata out of /opt.
  tar -C "$REPO_ROOT" \
    -cf - \
    LICENSE \
    Makefile \
    README.md \
    pyproject.toml \
    requirements.txt \
    config \
    docs \
    examples \
    src | tar -C "$APP_SRC_DIR" -xf -

  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install "$APP_SRC_DIR"
  rm -rf "$APP_SRC_DIR/build" "$APP_SRC_DIR"/src/*.egg-info
}

write_install_info() {
  log "Writing install metadata to ${INSTALL_INFO_FILE}"
  : > "$INSTALL_INFO_FILE"

  local app_version
  app_version="$("$VENV_DIR/bin/python" - <<'PYAPPVERSION'
from importlib.metadata import version
print(version("fmbcb-rds-multi-scan"))
PYAPPVERSION
)"

  write_env_kv "APP_NAME" "$APP_NAME"
  write_env_kv "APP_VERSION" "$app_version"
  write_env_kv "INSTALLED_AT_UTC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_env_kv "PREFIX" "$PREFIX"
  write_env_kv "BIN_DIR" "$BIN_DIR"
  write_env_kv "CONFIG_DIR" "$CONFIG_DIR"
  write_env_kv "RX_SDR_PROFILE_CONFIG_FILE" "$RX_SDR_PROFILE_CONFIG_FILE"
  write_env_kv "BUILD_ROOT" "$BUILD_ROOT"
  write_env_kv "APP_SRC_DIR" "$APP_SRC_DIR"
  write_env_kv "VENV_DIR" "$VENV_DIR"
  write_env_kv "REPO_ROOT" "$REPO_ROOT"
  write_env_kv "REPO_GIT_BRANCH" "$(git_branch_for_dir "$REPO_ROOT")"
  write_env_kv "REPO_GIT_COMMIT" "$(git_commit_for_dir "$REPO_ROOT")"
  write_env_kv "REPO_GIT_DIRTY" "$(git_dirty_for_dir "$REPO_ROOT")"
  write_env_kv "RX_TOOLS_REPO" "$RX_TOOLS_REPO"
  write_env_kv "RX_TOOLS_REF" "$RX_TOOLS_REF"
  write_env_kv "RX_TOOLS_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/rx_tools")"
  write_env_kv "CSDR_REPO" "$CSDR_REPO"
  write_env_kv "CSDR_REF" "$CSDR_REF"
  write_env_kv "CSDR_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/csdr")"
  write_env_kv "REDSEA_REPO" "$REDSEA_REPO"
  write_env_kv "REDSEA_REF" "$REDSEA_REF"
  write_env_kv "REDSEA_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/redsea")"
  write_env_kv "SDRPLAY_API_URL" "$SDRPLAY_API_URL"
  write_env_kv "SDRPLAY_API_INSTALLER" "$SDRPLAY_API_INSTALLER"
  write_env_kv "SDRPLAY_API_SERVICE" "$SDRPLAY_API_SERVICE"
  write_env_kv "SDRPLAY_API_SERVICE_ACTIVE" "$(systemctl is-active "$SDRPLAY_API_SERVICE" 2>/dev/null || true)"
  write_env_kv "SOAPY_SDRPLAY_REPO" "$SOAPY_SDRPLAY_REPO"
  write_env_kv "SOAPY_SDRPLAY_REF" "$SOAPY_SDRPLAY_REF"
  write_env_kv "SOAPY_SDRPLAY_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/SoapySDRPlay3")"
  if soapy_sdrplay_module_loaded; then
    write_env_kv "SOAPY_SDRPLAY_MODULE_LOADED" "yes"
  else
    write_env_kv "SOAPY_SDRPLAY_MODULE_LOADED" "no"
  fi
  write_env_kv "SOAPY_AIRSPYHF_REPO" "$SOAPY_AIRSPYHF_REPO"
  write_env_kv "SOAPY_AIRSPYHF_REF" "$SOAPY_AIRSPYHF_REF"
  write_env_kv "SOAPY_AIRSPYHF_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/SoapyAirspyHF")"
  write_env_kv "SOAPY_PLUTOSDR_REPO" "$SOAPY_PLUTOSDR_REPO"
  write_env_kv "SOAPY_PLUTOSDR_REF" "$SOAPY_PLUTOSDR_REF"
  write_env_kv "SOAPY_PLUTOSDR_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/SoapyPlutoSDR")"
  write_env_kv "SOAPY_FCDPP_REPO" "$SOAPY_FCDPP_REPO"
  write_env_kv "SOAPY_FCDPP_REF" "$SOAPY_FCDPP_REF"
  write_env_kv "SOAPY_FCDPP_COMMIT" "$(git_commit_for_dir "${BUILD_ROOT}/SoapyFCDPP")"
  write_env_kv "RX_SDR_COMMAND" "$(command -v rx_sdr || true)"
  write_env_kv "CSDR_COMMAND" "$(command -v csdr || true)"
  write_env_kv "REDSEA_COMMAND" "$(command -v redsea || true)"

  chmod 0644 "$INSTALL_INFO_FILE"
}

install_wrappers() {
  log "Installing command wrappers in ${BIN_DIR}"
  cat > "${BIN_DIR}/${APP_NAME}" <<EOF
#!/usr/bin/env bash
export FMB_RX_SDR_PROFILES="${RX_SDR_PROFILE_CONFIG_FILE}"
exec "${VENV_DIR}/bin/${APP_NAME}" "\$@"
EOF
  cat > "${BIN_DIR}/fmbcb-rds-env-check" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/fmbcb-rds-env-check" "\$@"
EOF
  chmod 0755 "${BIN_DIR}/${APP_NAME}" "${BIN_DIR}/fmbcb-rds-env-check"
}

main() {
  if [[ "$DRY_RUN" == "1" ]]; then
    print_dry_run
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    echo "Please run as root, for example: sudo ./install.sh" >&2
    exit 1
  fi

  install_apt_deps
  reload_limesdr_udev_rules
  mkdir -p "$BUILD_ROOT"
  install_sdrplay_support
  build_soapy_extra_modules
  build_rx_sdr
  build_csdr
  build_redsea
  install_rtl_blacklist
  install_python_app
  install_rx_sdr_profile_config
  write_install_info
  install_wrappers

  log "Running environment checker"
  if ! "${BIN_DIR}/fmbcb-rds-env-check"; then
    warn "Install completed, but the environment checker reported problems. Review the messages above."
  fi

  print_soapy_support

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
