#!/usr/bin/env bash
# clean-target.sh — delete the target/ directory of the workspace root and of
# every crate. The submodule satellite crates (compograph, autostart, tray,
# global-hotkey, gpui-image) keep their own lockfiles and build independently,
# so their nested target/ directories are removed too.
#
# Usage:
#   script/clean-target.sh [--dry-run]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

dry_run=0
case "${1:-}" in
  --dry-run) dry_run=1 ;;
  "") ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

targets=()
[ -d target ] && targets+=(target)
for dir in crates/*/; do
  [ -d "${dir}target" ] && targets+=("${dir}target")
done

if [ ${#targets[@]} -eq 0 ]; then
  echo "No target directories found."
  exit 0
fi

freed_kb=0
for t in "${targets[@]}"; do
  kb=$(du -sk "$t" 2>/dev/null | cut -f1)
  freed_kb=$((freed_kb + kb))
  printf '  %8s  %s\n' "$(du -sh "$t" | cut -f1)" "$t"
done

if [ "$dry_run" -eq 1 ]; then
  echo "Dry run: nothing deleted (${#targets[@]} directories, ~$(awk "BEGIN{printf \"%.1f\", $freed_kb/1024/1024}") GiB)."
  exit 0
fi

rm -rf "${targets[@]}"
echo "Removed ${#targets[@]} target directories, freed ~$(awk "BEGIN{printf \"%.1f\", $freed_kb/1024/1024}") GiB."
