#!/usr/bin/env bash
# verify-submodules.sh — one-command verification for the five submodule
# satellite crates, run on the local machine (no CI involved).
#
# Usage:
#   bash script/verify-submodules.sh [--fast]
#
#   --fast  additionally build every entry with the gpui-fast flavor
#           (--no-default-features --features gpui-fast). The default run only
#           builds the gpui-kit flavor.
#
# The script performs:
#   1. Pin consistency: every submodule's gpui-pre / gpui-fast requirement must
#      equal the host root Cargo.toml pins.
#   2. Compile matrix: each manual-verification entry builds on the host
#      platform for the selected flavor(s).
#
# Exit code: 0 when all checks pass, non-zero otherwise.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

failures=0
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

# ---------------------------------------------------------------------------
# 1. Pin consistency
# ---------------------------------------------------------------------------
echo "== pin consistency =="
# Host pins from the root Cargo.toml.
HOST_PRE=$(sed -n 's/^gpui = { package = "gpui-pre", version = "=\(.*\)".*/\1/p' "$ROOT/Cargo.toml")
HOST_FAST=$(sed -n 's/^gpui-fast = { package = "gpui-fast", version = "\([^"]*\)".*/\1/p' "$ROOT/Cargo.toml")
HOST_PRE_PLATFORM=$(sed -n 's/^gpui_platform = { package = "gpui-pre-platform", version = "=\(.*\)".*/\1/p' "$ROOT/Cargo.toml")
echo "host pins: gpui-pre =$HOST_PRE / gpui-fast $HOST_FAST / gpui-pre-platform =$HOST_PRE_PLATFORM"

if [ -z "$HOST_PRE" ] || [ -z "$HOST_FAST" ]; then
    fail "could not read the host gpui pins from the root Cargo.toml"
fi

# Check one manifest: its gpui-pre and gpui-fast requirements must match the
# host. $1 = label, $2 = Cargo.toml path.
check_manifest_pins() {
    local label="$1" manifest="$2" ver_pre ver_fast
    [ -f "$manifest" ] || { fail "$label: manifest $manifest not found"; return; }
    ver_pre=$(sed -n 's/.*gpui-pre", version = "=\(.*\)".*/\1/p' "$manifest" | head -1)
    ver_fast=$(sed -n 's/.*gpui-fast", version = "\(.*\)".*/\1/p' "$manifest" | head -1)
    if [ -n "$ver_pre" ] && [ "$ver_pre" != "$HOST_PRE" ]; then
        fail "$label: gpui-pre =$ver_pre != host =$HOST_PRE"
    else
        echo "  ok $label: gpui-pre =$ver_pre"
    fi
    if [ -n "$ver_fast" ] && [ "$ver_fast" != "$HOST_FAST" ]; then
        fail "$label: gpui-fast $ver_fast != host $HOST_FAST"
    else
        echo "  ok $label: gpui-fast $ver_fast"
    fi
}

check_manifest_pins "compograph" "$ROOT/crates/compograph/Cargo.toml"
check_manifest_pins "tray" "$ROOT/crates/tray/Cargo.toml"
check_manifest_pins "autostart" "$ROOT/crates/autostart/Cargo.toml"
check_manifest_pins "global-hotkey" "$ROOT/crates/global-hotkey/Cargo.toml"
check_manifest_pins "gpui-image" "$ROOT/crates/gpui-image/Cargo.toml"

# gpui-kit version pin in gpui-image (component layer).
IMG_KIT=$(sed -n 's/.*gpui-component = { version = "=\(.*\)".*/\1/p' "$ROOT/crates/gpui-image/Cargo.toml" | head -1)
HOST_KIT=$(sed -n 's/^gpui-component = { path = "crates\/component", version = "\(.*\)".*/\1/p' "$ROOT/Cargo.toml")
if [ -n "$IMG_KIT" ] && [ "$IMG_KIT" != "$HOST_KIT" ]; then
    fail "gpui-image: gpui-component =$IMG_KIT != host $HOST_KIT"
else
    echo "  ok gpui-image: gpui-component =$IMG_KIT"
fi

# ---------------------------------------------------------------------------
# 2. Compile matrix
# ---------------------------------------------------------------------------
# Each command runs in its submodule directory; a failing build is recorded.
# One entry per line: "label<TAB>directory<TAB>command".
build_one() {
    local label="$1" dir="$2"; shift 2
    echo "== build: $label =="
    (cd "$dir" && "$@") > /tmp/verify-submodules-last.log 2>&1
    local code=$?
    if [ $code -ne 0 ]; then
        fail "$label build failed (exit $code); tail of the log:"
        tail -5 /tmp/verify-submodules-last.log | sed 's/^/    /'
    else
        echo "  ok $label"
    fi
}

matrix() {
    # gpui-kit flavor (default features).
    build_one "hotkey_probe"     "$ROOT/crates/global-hotkey" cargo build -p hotkey_probe
    build_one "autostart CLI"    "$ROOT/crates/autostart"     cargo build --example autostart
    build_one "tray_lifecycle"   "$ROOT/crates/tray"          cargo build -p tray_lifecycle
    build_one "image_demo"       "$ROOT/crates/gpui-image"    cargo build -p image_demo
    build_one "compograph"       "$ROOT/crates/compograph"    cargo build -p compograph

    if [ $FAST -eq 1 ]; then
        build_one "hotkey_probe (fast)"   "$ROOT/crates/global-hotkey" cargo build -p hotkey_probe --no-default-features --features gpui-fast
        build_one "autostart CLI (fast)"  "$ROOT/crates/autostart"     cargo build --example autostart --no-default-features --features gpui-fast
        build_one "tray_lifecycle (fast)" "$ROOT/crates/tray"          cargo build -p tray_lifecycle --no-default-features --features gpui-fast
        build_one "image_demo (fast)"     "$ROOT/crates/gpui-image"    cargo build -p image_demo --no-default-features --features gpui-fast
    fi
}

matrix

echo
if [ $failures -eq 0 ]; then
    echo "verify-submodules: OK"
    exit 0
else
    echo "verify-submodules: $failures failure(s)"
    exit 1
fi
