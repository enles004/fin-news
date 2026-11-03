#!/usr/bin/env bash
set -e

# Fin-News Launcher for Linux and macOS

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_PATH="$SCRIPT_DIR/core/cli.py"

# 1. Check for standard python >= 3.11
for py_cmd in python3 python; do
    if command -v "$py_cmd" >/dev/null 2>&1; then
        if "$py_cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
            exec "$py_cmd" "$CLI_PATH" "$@"
        fi
    fi
done

# 2. Check for uv
if command -v uv >/dev/null 2>&1; then
    exec uv run python "$CLI_PATH" "$@"
fi

# 3. Ask user before installing uv (never silent)
echo "Python 3.11+ or uv was not found on your system."
read -p "Would you like to install uv to your user directory (no root required)? (y/N): " choice
case "$choice" in
    [yY][eE][sS]|[yY])
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        echo "Installing Python 3.12 via uv..."
        uv python install 3.12
        exec uv run python "$CLI_PATH" "$@"
        ;;
    *)
        echo "Installation cancelled. Please install Python 3.11+ or uv manually: https://astral.sh/uv"
        exit 1
        ;;
esac
