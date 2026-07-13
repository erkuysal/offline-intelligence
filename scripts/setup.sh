#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${OIH_CONDA_ENV:-offline-ai}"
INSTALL_WEB=true
INSTALL_BROWSER=false
DRY_RUN=false
INTERACTIVE_MODE=auto
ASSUME_YES=false
MODE_CHOICE_SET=false
WEB_CHOICE_SET=false
BROWSER_CHOICE_SET=false

usage() {
  cat <<'EOF'
Usage: ./scripts/setup.sh [options]

Create or update the local development environment.

Options:
  --backend-only    Skip Node.js dependency installation
  --with-browser    Install Playwright's Chromium browser for E2E tests
  --interactive     Force the interactive setup wizard
  --automatic       Use selected/default components without further prompts
  -y, --yes         Alias for --automatic (useful for automation)
  --dry-run         Print commands without changing the system
  -h, --help        Show this help

Environment:
  OIH_CONDA_ENV     Override the Conda environment name (default: offline-ai)
EOF
}

log() {
  printf '[setup] %s\n' "$*"
}

run() {
  if [[ "$DRY_RUN" == true ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if [[ "$DRY_RUN" == false ]] && ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n%s\n' "$command_name" "$install_hint" >&2
    exit 2
  fi
}

prompt_yes_no() {
  local prompt="$1"
  local default_answer="$2"
  local answer

  while true; do
    if ! read -r -p "$prompt" answer; then
      printf '\nInput closed; setup cancelled.\n' >&2
      exit 2
    fi
    answer="${answer:-$default_answer}"
    case "${answer,,}" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) printf 'Please answer yes or no.\n' ;;
    esac
  done
}

prompt_setup_mode() {
  local answer

  while true; do
    if ! read -r -p 'Setup mode: [I]nteractive / [A]utomatic (default: Interactive) ' answer; then
      printf '\nInput closed; setup cancelled.\n' >&2
      exit 2
    fi
    answer="${answer:-interactive}"
    case "${answer,,}" in
      i|interactive) INTERACTIVE_MODE=true; return ;;
      a|automatic|auto) INTERACTIVE_MODE=false; ASSUME_YES=true; return ;;
      *) printf 'Please choose Interactive or Automatic.\n' ;;
    esac
  done
}

while (($#)); do
  case "$1" in
    --backend-only)
      INSTALL_WEB=false
      WEB_CHOICE_SET=true
      ;;
    --with-browser)
      INSTALL_BROWSER=true
      BROWSER_CHOICE_SET=true
      ;;
    --interactive)
      INTERACTIVE_MODE=true
      MODE_CHOICE_SET=true
      ;;
    --automatic|-y|--yes|--non-interactive)
      INTERACTIVE_MODE=false
      ASSUME_YES=true
      MODE_CHOICE_SET=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$DRY_RUN" == true && "$INTERACTIVE_MODE" == auto && ! -t 0 ]]; then
  INTERACTIVE_MODE=false
elif [[ "$INTERACTIVE_MODE" == auto ]]; then
  if [[ -t 0 && -t 1 ]]; then
    printf 'Offline Intelligence Hub setup\n\n'
    prompt_setup_mode
  else
    INTERACTIVE_MODE=false
  fi
fi

if [[ "$INTERACTIVE_MODE" == true ]]; then
  if [[ "$MODE_CHOICE_SET" == true ]]; then
    printf 'Offline Intelligence Hub interactive setup\n\n'
  fi
  if [[ "$WEB_CHOICE_SET" == false ]]; then
    if prompt_yes_no 'Install frontend dependencies? [Y/n] ' yes; then
      INSTALL_WEB=true
    else
      INSTALL_WEB=false
    fi
  fi
  if [[ "$INSTALL_WEB" == true && "$BROWSER_CHOICE_SET" == false ]]; then
    if prompt_yes_no 'Install Playwright Chromium for browser tests? [y/N] ' no; then
      INSTALL_BROWSER=true
    else
      INSTALL_BROWSER=false
    fi
  fi
fi

if [[ "$INSTALL_BROWSER" == true && "$INSTALL_WEB" == false ]]; then
  printf '%s\n' '--with-browser cannot be combined with --backend-only.' >&2
  exit 2
fi

require_command conda "Install Miniconda or Anaconda, then reopen your shell."
if [[ "$INSTALL_WEB" == true ]]; then
  require_command node "Install Node.js 20.19+ or 22.12+."
  require_command npm "Install npm with Node.js."
  if [[ "$DRY_RUN" == false ]] && ! node -e '
    const [major, minor] = process.versions.node.split(".").map(Number)
    process.exit((major === 20 && minor >= 19) || major >= 22 ? 0 : 1)
  '; then
    printf 'Unsupported Node.js version: %s\nUse Node.js ^20.19.0 or >=22.12.0.\n' "$(node --version)" >&2
    exit 2
  fi
fi

cd "$ROOT_DIR"

ENV_EXISTS=false
ENV_ACTION=create
ENV_PREFIX="$(conda info --base 2>/dev/null || printf '<conda-base>')/envs/${ENV_NAME}"
if command -v conda >/dev/null 2>&1 && conda run -n "$ENV_NAME" python --version >/dev/null 2>&1; then
  ENV_EXISTS=true
  ENV_ACTION=update
  ENV_PREFIX="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.prefix)')"
fi

if [[ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ]]; then
  BROWSER_PATH="$PLAYWRIGHT_BROWSERS_PATH"
else
  BROWSER_PATH="${HOME:-<home>}/.cache/ms-playwright"
fi

printf '\nInstallation plan\n'
printf '  Project root:       %s\n' "$ROOT_DIR"
printf '  Conda environment:  %s (%s)\n' "$ENV_NAME" "$ENV_ACTION"
printf '  Conda location:     %s\n' "$ENV_PREFIX"
printf '  Backend packages:   %s/requirements.txt\n' "$ROOT_DIR"
if [[ "$INSTALL_WEB" == true ]]; then
  printf '  Frontend packages:  %s/apps/web/node_modules (npm ci)\n' "$ROOT_DIR"
else
  printf '  Frontend packages:  skipped\n'
fi
if [[ "$INSTALL_BROWSER" == true ]]; then
  printf '  Playwright browser: %s\n' "$BROWSER_PATH"
else
  printf '  Playwright browser: skipped\n'
fi
if [[ -e config/env/local.env ]]; then
  printf '  Local config:       %s/config/env/local.env (preserved)\n' "$ROOT_DIR"
else
  printf '  Local config:       %s/config/env/local.env (create from example)\n' "$ROOT_DIR"
fi
printf '  Runtime data:       %s/var/{cache,models,run,storage}\n' "$ROOT_DIR"
printf '  Docker services:    not started\n'
printf '  Model weights:      not downloaded\n\n'

if [[ "$INTERACTIVE_MODE" == true ]]; then
  if ! prompt_yes_no 'Proceed with this installation? [y/N] ' no; then
    log "Setup cancelled; no installation commands were run"
    exit 0
  fi
elif [[ "$DRY_RUN" == false && "$ASSUME_YES" == true ]]; then
  log "Automatic mode; proceeding with the plan above"
elif [[ "$DRY_RUN" == false ]]; then
  printf 'No interactive terminal is available. Review the plan above, then rerun with --yes.\n' >&2
  exit 2
fi

log "Preparing Conda environment: ${ENV_NAME}"
if [[ "$ENV_EXISTS" == true ]]; then
  run conda env update --name "$ENV_NAME" --file environment.yml --prune
else
  run conda env create --name "$ENV_NAME" --file environment.yml
fi

log "Installing pinned backend dependencies"
run conda run -n "$ENV_NAME" python -m pip install --requirement requirements.txt

if [[ "$INSTALL_WEB" == true ]]; then
  log "Installing locked frontend dependencies"
  run npm --prefix apps/web ci

  if [[ "$INSTALL_BROWSER" == true ]]; then
    log "Installing Playwright Chromium"
    run npm --prefix apps/web exec -- playwright install chromium
  fi
fi

log "Preparing local configuration and runtime directories"
run mkdir -p var/cache var/models var/run var/storage/documents
if [[ -e config/env/local.env ]]; then
  log "Keeping existing config/env/local.env"
elif [[ "$DRY_RUN" == true ]]; then
  run cp config/env/local.example.env config/env/local.env
  log "Would create config/env/local.env from the example"
else
  run cp config/env/local.example.env config/env/local.env
  log "Created config/env/local.env from the example"
fi

if [[ "$DRY_RUN" == false ]]; then
  conda run -n "$ENV_NAME" python manage.py --help >/dev/null
  ACTUAL_PREFIX="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.prefix)')"
  SITE_PACKAGES="$(conda run -n "$ENV_NAME" python -c 'import site; print(site.getsitepackages()[0])')"

  printf '\nInstalled locations\n'
  printf '  Conda environment:  %s\n' "$ACTUAL_PREFIX"
  printf '  Python packages:    %s\n' "$SITE_PACKAGES"
  if [[ "$INSTALL_WEB" == true ]]; then
    printf '  Frontend packages:  %s\n' "$(npm --prefix apps/web root)"
  fi
  if [[ "$INSTALL_BROWSER" == true ]]; then
    printf '  Playwright browser: %s\n' "$BROWSER_PATH"
  fi
  printf '  Local config:       %s/config/env/local.env\n' "$ROOT_DIR"
  printf '  Runtime data:       %s/var\n' "$ROOT_DIR"
fi

log "Setup complete"
printf '\nNext steps:\n'
printf '  conda activate %s\n' "$ENV_NAME"
printf '  docker compose -f deploy/compose.yaml up -d postgres redis\n'
printf '  ./manage.py migrate\n'
printf '  ./manage.py runserver\n'
printf '\nSee docs/installation.md for testing, browser, and troubleshooting instructions.\n'
