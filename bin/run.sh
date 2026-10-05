#!/usr/bin/env bash
cd "$(dirname "$(realpath "$0")")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

set -eu

IS_APPIMAGE=${APPIMAGE:-}

# Check if notify-send exists globally
if command -v notify-send &> /dev/null; then
    NOTIFY_SEND_AVAILABLE=0
else
    NOTIFY_SEND_AVAILABLE=1
fi

# Logging functions
notify() {
    if [ "$NOTIFY_SEND_AVAILABLE" -eq 0 ]; then
        notify-send -t 5000 -u "$1" "$2" "$3" 2>/dev/null || true
    fi
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
    notify normal INFO "$1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    notify normal WARNING "$1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    notify critical ERROR "$1"
}

# Parse command line arguments
SETUP_VENV=false
PYTHON_ARGS=()

for arg in "$@"; do
    if [ "$arg" = "--venv" ]; then
        SETUP_VENV=true
    else
        PYTHON_ARGS+=("$arg")
    fi
done

setup_venv() {
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi

    source .venv/bin/activate

    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        log_warn "requirements.txt not found, skipping pip install"
    fi
}

# Check if we're running inside an AppImage
if [ -n "$IS_APPIMAGE" ]; then
    # We are using the bundled standalone python
    PYTHON_EXEC=".venv/bin/python3"

    if [ -f "$PYTHON_EXEC" ]; then
        exec "$PYTHON_EXEC" src/main.py "${PYTHON_ARGS[@]}"
    else
        log_error "Bundled Python environment not found in AppImage"
        exit 1
    fi
else
    if [ "$SETUP_VENV" = true ]; then
        log_info "Setting up virtual environment and installing dependencies"
        setup_venv
    elif [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    else
        log_warn "No virtual environment found, creating"
        setup_venv
    fi

    # Preserves DISPLAY, WAYLAND_DISPLAY, PATH, etc. needed for Qt GUI and Wine
    exec python src/main.py "${PYTHON_ARGS[@]}"
fi
