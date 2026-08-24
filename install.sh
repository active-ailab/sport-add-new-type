#!/usr/bin/env sh
# Owner: cs-dongqi@zepp.com
# Organization: Active.Bu
set -eu

APP_NAME="${APP_NAME:-sport-proto}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
SOURCE="$PROJECT_DIR/cli/bin/sport-proto"

[ -f "$SOURCE" ] || { echo "ERROR: missing CLI entry: $SOURCE" >&2; exit 1; }
mkdir -p "$BIN_DIR"
ln -sfn "$SOURCE" "$BIN_DIR/$APP_NAME"
echo "installed: $BIN_DIR/$APP_NAME -> $SOURCE"
