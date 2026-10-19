#!/usr/bin/env bash
# Verify that the host workspace pins the exact same `gpui-pre` snapshot that is
# actually resolved in Cargo.lock. Since gpui-kit inherits the `gpui` dependency
# through `[workspace.dependencies]`, this guarantees one GPUI type universe is
# linked into the process (the failure mode called out in
# docs/plan/tray-menubar-feature.md).
#
# Usage: ./script/check-gpui-pin.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The pinned requirement, e.g. `=0.3.9` -> `0.3.9`.
host_pin=$(sed -n '/^\[workspace.dependencies\]/,/^\[/p' Cargo.toml \
  | grep -A2 'gpui = { package = "gpui-pre"' \
  | grep -oE 'version = "=?[0-9][0-9.]*"' \
  | head -1 \
  | sed -E 's/.*"=?([0-9.]+)"/\1/')

# The version actually resolved into Cargo.lock for the gpui-pre package.
locked_pin=$(grep -A3 'name = "gpui-pre"' Cargo.lock \
  | grep -oE 'version = "[0-9][0-9.]*"' \
  | head -1 \
  | sed -E 's/version = "([0-9.]+)"/\1/')

if [ -z "$host_pin" ] || [ -z "$locked_pin" ]; then
  echo "Unable to determine gpui-pre pins (host='$host_pin' locked='$locked_pin')" >&2
  exit 1
fi

echo "workspace gpui-pre pin : $host_pin"
echo "resolved gpui-pre version : $locked_pin"

if [ "$host_pin" != "$locked_pin" ]; then
  echo "MISMATCH: the workspace must pin the same gpui-pre snapshot that is resolved." >&2
  exit 1
fi

# gpui-kit must inherit the pinned `gpui` dependency rather than re-declaring its
# own version, so there is a single source of truth.
if ! grep -q 'gpui = { workspace = true }' crates/kit/Cargo.toml; then
  echo "WARNING: crates/kit does not inherit gpui via 'workspace = true'." >&2
fi

echo "OK: gpui-pre pins are aligned."
