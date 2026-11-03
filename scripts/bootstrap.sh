#!/usr/bin/env bash
# Prepare a local LearnFlux development/runtime environment without replacing user config.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_TEMPLATE="$ROOT_DIR/config/config.example.jsonc"
CONFIG_PATH="${LEARNFLUX_CONFIG_PATH:-$ROOT_DIR/config/config.jsonc}"
INSTALL_LOCAL_WHISPER=false
INSTALL_MEDIA=false
INSTALL_DEV=false

info() { printf '[LearnFlux] %s\n' "$*"; }
fail() { printf '[LearnFlux] Error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: bash scripts/bootstrap.sh [--with-media] [--with-local-whisper] [--dev]

Installs the LearnFlux Python dependencies and creates a private local
configuration only when it does not exist. Text learning needs no ASR setup.

Options:
  --with-media          Ensure FFmpeg is available for audio/video processing.
  --with-local-whisper  Install mlx-whisper for Apple Silicon macOS.
  --dev                 Also install the test dependencies.
  -h, --help            Show this help text.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-local-whisper) INSTALL_LOCAL_WHISPER=true; INSTALL_MEDIA=true ;;
        --with-media) INSTALL_MEDIA=true ;;
        --dev) INSTALL_DEV=true ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
        return
    fi

    command -v curl >/dev/null 2>&1 || fail "curl is required to install uv"
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    for candidate in "${HOME}/.local/bin/uv" "${HOME}/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            UV_BIN="$candidate"
            return
        fi
    done
    fail "uv was installed but is not on PATH; open a new shell and run this command again"
}

ensure_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1; then
        return
    fi

    case "$(uname -s)" in
        Darwin)
            command -v brew >/dev/null 2>&1 || fail "Install Homebrew first, then run: brew install ffmpeg"
            info "Installing FFmpeg with Homebrew..."
            brew install ffmpeg
            ;;
        Linux)
            command -v apt-get >/dev/null 2>&1 || fail "Install FFmpeg with your distribution package manager, then run this command again"
            info "Installing FFmpeg with apt..."
            sudo apt-get update
            sudo apt-get install -y ffmpeg
            ;;
        *)
            fail "Install FFmpeg manually for $(uname -s), then run this command again"
            ;;
    esac
}

install_local_whisper() {
    [ "$(uname -s)" = "Darwin" ] || fail "--with-local-whisper is supported only on macOS Apple Silicon"
    [ "$(uname -m)" = "arm64" ] || fail "--with-local-whisper requires an Apple Silicon Mac"

    local whisper_venv="${LEARNFLUX_MLX_VENV:-${HOME}/.venvs/mlx-whisper}"
    info "Installing mlx-whisper into $whisper_venv..."
    "$UV_BIN" venv --python 3.11 "$whisper_venv"
    "$UV_BIN" pip install --python "$whisper_venv/bin/python" mlx-whisper
    cat <<EOF

[LearnFlux] Local transcription is installed. Enable it in config/config.jsonc:
"local_whisper": {
    "enabled": true,
    "binary": "$whisper_venv/bin/mlx_whisper",
    "model": "mlx-community/whisper-large-v3-turbo",
    "language": "",
    "timeout": 1800
}
EOF
}

ensure_uv
if [ -z "${LEARNFLUX_CONFIG_PATH:-}" ] && [ ! -e "$CONFIG_PATH" ] && [ -e "$ROOT_DIR/config/config.json" ]; then
    fail "Found legacy config/config.json. Preserve it and migrate it to config/config.jsonc before running bootstrap."
fi

info "Installing LearnFlux dependencies..."
if [ "$INSTALL_DEV" = true ]; then
    (cd "$ROOT_DIR" && "$UV_BIN" sync --frozen --python 3.11 --extra dev)
else
    (cd "$ROOT_DIR" && "$UV_BIN" sync --frozen --python 3.11)
fi

(cd "$ROOT_DIR" && "$UV_BIN" run --no-sync python scripts/init_config.py --output "$CONFIG_PATH" --template "$CONFIG_TEMPLATE")

if [ "$INSTALL_MEDIA" = true ]; then
    ensure_ffmpeg
fi

if [ "$INSTALL_LOCAL_WHISPER" = true ]; then
    install_local_whisper
fi

info "Bootstrap complete. Start the service: bash server.sh start"
info "Configure private model/platform credentials and your selected ASR; follow the README real-link acceptance steps."
info "Default settings URL: http://127.0.0.1:8000/settings (adjust for your configured port)."
