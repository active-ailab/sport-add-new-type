#!/usr/bin/env sh
# Owner: cs-dongqi@zepp.com
# Organization: Active.Bu
set -eu

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
mkdir -p "$BIN_DIR"

echo "installing Python dependencies from $PROJECT_DIR/cli"
python3 -m pip install --user "$PROJECT_DIR/cli"

if [ -n "${APP_NAME:-}" ]; then
  SOURCE="$PROJECT_DIR/cli/bin/sport-proto"
  [ -f "$SOURCE" ] || { echo "ERROR: missing CLI entry: $SOURCE" >&2; exit 1; }
  ln -sfn "$SOURCE" "$BIN_DIR/$APP_NAME"
  echo "installed: $BIN_DIR/$APP_NAME -> $SOURCE"
  exit 0
fi

for APP in sport-proto sport-config; do
  SOURCE="$PROJECT_DIR/cli/bin/$APP"
  [ -f "$SOURCE" ] || { echo "ERROR: missing CLI entry: $SOURCE" >&2; exit 1; }
  ln -sfn "$SOURCE" "$BIN_DIR/$APP"
  echo "installed: $BIN_DIR/$APP -> $SOURCE"
done
