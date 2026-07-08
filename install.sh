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
DRY_RUN="${FMB_DRY_RUN:-0}"

RX_TOOLS_REPO="${FMB_RX_TOOLS_REPO:-https://github.com/rxseger/rx_tools}"
RX_TOOLS_REF="${FMB_RX_TOOLS_REF:-}"
CSDR_REPO="${FMB_CSDR_REPO:-https://github.com/ha7ilm/csdr.git}"
CSDR_REF="${FMB_CSDR_REF:-}"
REDSEA_REPO="${FMB_REDSEA_REPO:-https://github.com/windytan/redsea.git}"
REDSEA_REF="${FMB_REDSEA_REF:-}"

usage() {
  cat <<EOF
Usage: sudo ./install.sh [options]

Install ${APP_NAME}, create a Python virtual environment, install wrappers, and
build missing native SDR tools when needed. Distro SoapySDR packages are
installed through APT when available; SDRplay API and SoapySDRPlay3 remain a
manual install path documented in docs/INSTALL.md.

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
  --dry-run, --check         Validate options and print the install plan
  -h, --help                 Show this help

Environment overrides:
  FMB_RX_TOOLS_REPO, FMB_RX_TOOLS_REF
  FMB_CSDR_REPO, FMB_CSDR_REF
  FMB_REDSEA_REPO, FMB_REDSEA_REF

Notes:
  SDRplay users still need the SDRplay API and SoapySDRPlay3 installed
  separately. See docs/INSTALL.md.
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

validate_install_paths() {
  validate_install_path "--prefix/FMB_PREFIX" "$PREFIX"
  validate_install_path "--bin-dir/FMB_BIN_DIR" "$BIN_DIR"
  validate_install_path "--build-root/FMB_BUILD_ROOT" "$BUILD_ROOT"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) require_option_value "$1" "${2-}"; PREFIX="$2"; shift 2 ;;
    --bin-dir) require_option_value "$1" "${2-}"; BIN_DIR="$2"; shift 2 ;;
    --build-root) require_option_value "$1" "${2-}"; BUILD_ROOT="$2"; shift 2 ;;
    --force-build) FORCE_BUILD=1; shift ;;
    --skip-apt) SKIP_APT=1; shift ;;
    --skip-native-build) SKIP_NATIVE_BUILD=1; shift ;;
    --skip-rx-sdr-build) SKIP_RX_SDR_BUILD=1; shift ;;
    --skip-csdr-build) SKIP_CSDR_BUILD=1; shift ;;
    --skip-redsea-build) SKIP_REDSEA_BUILD=1; shift ;;
    --install-rtl-blacklist) INSTALL_RTL_BLACKLIST=1; shift ;;
    --dry-run|--check) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

validate_install_paths

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PREFIX}/venv"
APP_SRC_DIR="${PREFIX}/src"
INSTALL_INFO_FILE="${PREFIX}/install-info.env"

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

APT_REQUIRED_PACKAGES=(
  ca-certificates curl git build-essential make cmake pkg-config
  python3 python3-venv python3-pip python3-dev
  libusb-1.0-0-dev libfftw3-dev libsndfile1-dev libliquid-dev
  meson ninja-build nlohmann-json3-dev
  soapysdr-tools libsoapysdr-dev usbutils
)

APT_OPTIONAL_PACKAGES=(
  soapysdr-module-rtlsdr rtl-sdr sox
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

apt_package_available() {
  apt-cache show "$1" >/dev/null 2>&1
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

print_dry_run() {
  cat <<EOF
${APP_NAME} install preflight

Paths:
  repo root:      ${REPO_ROOT}
  prefix:         ${PREFIX}
  bin dir:        ${BIN_DIR}
  build root:     ${BUILD_ROOT}
  venv:           ${VENV_DIR}
  app source:     ${APP_SRC_DIR}
  install info:   ${INSTALL_INFO_FILE}

Toggles:
  skip apt:             ${SKIP_APT}
  skip native build:    ${SKIP_NATIVE_BUILD}
  force build:          ${FORCE_BUILD}
  install RTL blacklist: ${INSTALL_RTL_BLACKLIST}

APT:
EOF

  if [[ "$SKIP_APT" == "1" ]]; then
    printf '  action: skip APT package install\n'
  else
    print_package_list "required packages" "${APT_REQUIRED_PACKAGES[@]}"
    print_package_list "optional packages" "${APT_OPTIONAL_PACKAGES[@]}"
  fi

  cat <<EOF

Native tools:
EOF
  print_native_plan "rx_sdr" "$SKIP_RX_SDR_BUILD" "$RX_TOOLS_REPO" "$RX_TOOLS_REF" "${BUILD_ROOT}/rx_tools"
  print_native_plan "csdr" "$SKIP_CSDR_BUILD" "$CSDR_REPO" "$CSDR_REF" "${BUILD_ROOT}/csdr"
  print_native_plan "redsea" "$SKIP_REDSEA_BUILD" "$REDSEA_REPO" "$REDSEA_REF" "${BUILD_ROOT}/redsea"

  cat <<EOF

Python app:
  action: create/update virtual environment and install curated source snapshot
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
  log "Updating APT package metadata"
  apt-get update

  log "Installing required Debian/Ubuntu packages"
  apt_install_required "${APT_REQUIRED_PACKAGES[@]}"

  log "Installing optional Debian/Ubuntu packages when available"
  apt_install_optional "${APT_OPTIONAL_PACKAGES[@]}"
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
  write_env_kv "RX_SDR_COMMAND" "$(command -v rx_sdr || true)"
  write_env_kv "CSDR_COMMAND" "$(command -v csdr || true)"
  write_env_kv "REDSEA_COMMAND" "$(command -v redsea || true)"

  chmod 0644 "$INSTALL_INFO_FILE"
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
  if [[ "$DRY_RUN" == "1" ]]; then
    print_dry_run
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    echo "Please run as root, for example: sudo ./install.sh" >&2
    exit 1
  fi

  install_apt_deps
  mkdir -p "$BUILD_ROOT"
  build_rx_sdr
  build_csdr
  build_redsea
  install_rtl_blacklist
  install_python_app
  write_install_info
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
