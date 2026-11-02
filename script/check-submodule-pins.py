#!/usr/bin/env python3
"""Verify that every submodule satellite pins the same GPUI backend as the host.

The host workspace (`Cargo.toml [workspace.dependencies]`) is the single
source of truth for the GPUI snapshot: `gpui-pre =x.y.z` (exact, see #3156),
`gpui-fast x.y.z`, and the Zed revision the snapshot was cut from
(`[workspace.metadata.gpui-kit] zed-rev`). Each submodule is an independent
repository with its own manifest (and sometimes its own lockfile), so nothing
forces its backend pins to move when the host bumps the snapshot -- `gpui-tray`
sat on `gpui-pre 0.3.9` / `gpui-fast 0.1.10` after the host moved to
`0.3.10` / `0.1.12`, and the upstream-git flavor of `gpui-autostart` /
`gpui-global-hotkey` still named the Zed commit of `0.3.9`. A mismatch
means two `gpui::App` types in one process, which stops compiling at best.

The check reads the host pins from the working tree and compares every
submodule manifest against them. It needs no network: the submodule
`check-gpui-kit-pin.py` scripts compare against the latest *published* GPUI
Kit release instead, which lags the working tree during snapshot bumps.

Usage:
    python3 script/check-submodule-pins.py [--fix]

`--fix` rewrites the stale `version` / `rev` values in the
submodule manifests in place. Committed lockfiles still need their own
`cargo update -p <pkg> --precise <version>` per submodule; the failure output
prints the exact commands.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST_MANIFEST = ROOT / "Cargo.toml"
HOST_LOCK = ROOT / "Cargo.lock"

ZED_GIT_URL = "https://github.com/zed-industries/zed.git"


@dataclass
class HostPins:
    pre_req: str  # e.g. "=0.3.10", exact by policy (#3156)
    pre_version: str  # e.g. "0.3.10"
    platform_req: str
    platform_features: list[str]
    fast_version: str  # e.g. "0.1.12", compared without the operator
    component_version: str  # e.g. "0.8.1", compared without the operator
    zed_rev: str  # the commit the pinned snapshot was cut from
    locked_pre: str | None  # resolved in the host lockfile, when present
    locked_fast: str | None


def pinned_version(requirement: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)*)", requirement)
    if match is None:
        raise SystemExit(f"cannot read a version out of {requirement!r}")
    return match.group(1)


def read_host() -> HostPins:
    manifest = tomllib.loads(HOST_MANIFEST.read_text())
    workspace = manifest.get("workspace", {})
    dependencies = workspace.get("dependencies", {})

    pre = dependencies.get("gpui", {})
    if pre.get("package") != "gpui-pre":
        raise SystemExit("host [workspace.dependencies] gpui no longer names gpui-pre")
    platform = dependencies.get("gpui_platform", {})
    fast = dependencies.get("gpui-fast", {})
    component = dependencies.get("gpui-component", {})
    try:
        zed_rev = workspace["metadata"]["gpui-kit"]["zed-rev"]
    except KeyError:
        raise SystemExit("host Cargo.toml is missing [workspace.metadata.gpui-kit] zed-rev")
    if not re.fullmatch(r"[0-9a-f]{40}", zed_rev):
        raise SystemExit(f"host zed-rev {zed_rev!r} is not a full commit hash")

    return HostPins(
        pre_req=pre["version"],
        pre_version=pinned_version(pre["version"]),
        platform_req=platform.get("version", ""),
        platform_features=list(platform.get("features", [])),
        fast_version=pinned_version(fast.get("version", "")),
        component_version=pinned_version(component.get("version", "")),
        zed_rev=zed_rev,
        locked_pre=locked_version(HOST_LOCK, "gpui-pre"),
        locked_fast=locked_version(HOST_LOCK, "gpui-fast"),
    )


def locked_version(lockfile: Path, package: str) -> str | None:
    if not lockfile.is_file():
        return None
    version: str | None = None
    current: str | None = None
    for line in lockfile.read_text().splitlines():
        name = re.match(r'name = "([^"]+)"', line.strip())
        if name is not None:
            current = name.group(1)
            continue
        if current == package:
            literal = re.match(r'version = "([^"]+)"', line.strip())
            if literal is not None:
                version = literal.group(1)
                current = None
    return version


@dataclass
class Mismatch:
    where: str
    detail: str
    fix: tuple[Path, str, str, str, str, str | None] | None = None
    # fix = (file, dependency key, TOML field, old value, new value, table scope)


def manifest_of(submodule: str) -> tuple[Path, dict]:
    path = ROOT / submodule / "Cargo.toml"
    if not path.is_file():
        raise SystemExit(
            f"submodule {submodule} is not checked out; run `git submodule update --init` first"
        )
    return path, tomllib.loads(path.read_text())


def all_dependency_tables(manifest: dict) -> list[tuple[str, dict]]:
    """Every table that can hold a dependency, with a dotted name for messages."""
    found: list[tuple[str, dict]] = []
    for table in ("dependencies", "dev-dependencies", "build-dependencies"):
        if isinstance(manifest.get(table), dict):
            found.append((table, manifest[table]))
    workspace = manifest.get("workspace", {})
    if isinstance(workspace.get("dependencies"), dict):
        found.append(("workspace.dependencies", workspace["dependencies"]))
    for target, tables in (manifest.get("target", {}) or {}).items():
        if not isinstance(tables, dict):
            continue
        for table in ("dependencies", "dev-dependencies", "build-dependencies"):
            if isinstance(tables.get(table), dict):
                found.append((f"target.{target}.{table}", tables[table]))
    return found


def find_dependency(manifest: dict, key: str, package: str | None = None) -> tuple[str, dict] | None:
    for table_name, table in all_dependency_tables(manifest):
        entry = table.get(key)
        if entry is None:
            continue
        if package is not None:
            if not isinstance(entry, dict) or entry.get("package") != package:
                continue
        if not isinstance(entry, dict):
            continue
        return table_name, entry
    return None


def check_exact_req(
    mismatches: list[Mismatch],
    path: Path,
    table: str,
    key: str,
    entry: dict,
    field: str,
    expected: str,
    label: str,
) -> None:
    actual = entry.get(field)
    if actual != expected:
        mismatches.append(
            Mismatch(
                where=f"{path.relative_to(ROOT)} [{table}] {key}",
                detail=f"{label}: pins {actual!r} but the host pins {expected!r}",
                fix=(path, key, field, actual, expected, table)
                if isinstance(actual, str)
                else None,
            )
        )


def check_version(
    mismatches: list[Mismatch],
    path: Path,
    table: str,
    key: str,
    entry: dict,
    expected_version: str,
    label: str,
) -> None:
    actual = entry.get("version")
    actual_version = pinned_version(actual) if isinstance(actual, str) else None
    if actual_version != expected_version:
        mismatches.append(
            Mismatch(
                where=f"{path.relative_to(ROOT)} [{table}] {key}",
                detail=f"{label}: pins {actual!r} but the host resolves {expected_version}",
                fix=(path, key, "version", actual, expected_version, table)
                if isinstance(actual, str)
                else None,
            )
        )


def check_zed_rev(
    mismatches: list[Mismatch],
    path: Path,
    table: str,
    key: str,
    entry: dict,
    expected_rev: str,
) -> None:
    if entry.get("git") != ZED_GIT_URL:
        return
    actual = entry.get("rev")
    if actual != expected_rev:
        mismatches.append(
            Mismatch(
                where=f"{path.relative_to(ROOT)} [{table}] {key}",
                detail=(
                    f"the upstream-git flavor names zed@{actual} but the host "
                    f"snapshot was cut from zed@{expected_rev}"
                ),
                fix=(path, key, "rev", actual, expected_rev, table)
                if isinstance(actual, str)
                else None,
            )
        )


def check_lock(
    mismatches: list[Mismatch], submodule: str, package: str, expected: str | None
) -> None:
    if expected is None:
        return
    lock = ROOT / submodule / "Cargo.lock"
    if not lock.is_file():
        return
    actual = locked_version(lock, package)
    if actual is None or actual != expected:
        mismatches.append(
            Mismatch(
                where=f"{lock.relative_to(ROOT)} {package}",
                detail=(
                    f"locks {actual!r} but the host resolves {expected}; run "
                    f"`cargo update -p {package} --precise {expected}` in {submodule}"
                ),
            )
        )


def check_tray(pins: HostPins, mismatches: list[Mismatch]) -> None:
    path, manifest = manifest_of("crates/tray")
    found = find_dependency(manifest, "gpui-kit-backend", "gpui-pre")
    if found is None:
        mismatches.append(Mismatch(where=str(path), detail="missing dependency gpui-kit-backend"))
    else:
        table, entry = found
        check_exact_req(
            mismatches, path, table, "gpui-kit-backend", entry, "version", pins.pre_req,
            "the gpui-pre snapshot",
        )
    found = find_dependency(manifest, "gpui-fast-backend", "gpui-fast")
    if found is None:
        mismatches.append(Mismatch(where=str(path), detail="missing dependency gpui-fast-backend"))
    else:
        table, entry = found
        check_version(
            mismatches, path, table, "gpui-fast-backend", entry, pins.fast_version,
            "the gpui-fast snapshot",
        )
    check_lock(mismatches, "crates/tray", "gpui-pre", pins.locked_pre)
    check_lock(mismatches, "crates/tray", "gpui-fast", pins.locked_fast)


def check_upstream_flavors(pins: HostPins, mismatches: list[Mismatch], submodule: str) -> None:
    path, manifest = manifest_of(submodule)
    found = find_dependency(manifest, "gpui-kit-backend", "gpui-pre")
    if found is None:
        mismatches.append(Mismatch(where=str(path), detail="missing dependency gpui-kit-backend"))
    else:
        table, entry = found
        check_exact_req(
            mismatches, path, table, "gpui-kit-backend", entry, "version", pins.pre_req,
            "the gpui-pre snapshot",
        )
    for table_name, table in all_dependency_tables(manifest):
        for key, entry in table.items():
            if isinstance(entry, dict):
                check_zed_rev(mismatches, path, table_name, key, entry, pins.zed_rev)


def check_image(pins: HostPins, mismatches: list[Mismatch]) -> None:
    path, manifest = manifest_of("crates/gpui-image")
    found = find_dependency(manifest, "gpui-kit-backend", "gpui-pre")
    if found is None:
        mismatches.append(Mismatch(where=str(path), detail="missing dependency gpui-kit-backend"))
    else:
        table, entry = found
        check_exact_req(
            mismatches, path, table, "gpui-kit-backend", entry, "version", pins.pre_req,
            "the gpui-pre snapshot",
        )
    found = find_dependency(manifest, "gpui-fast-backend", "gpui-fast")
    if found is None:
        mismatches.append(Mismatch(where=str(path), detail="missing dependency gpui-fast-backend"))
    else:
        table, entry = found
        check_version(mismatches, path, table, "gpui-fast-backend", entry, pins.fast_version, "the gpui-fast snapshot")
    found = find_dependency(manifest, "gpui-component", None)
    if found is not None:
        table, entry = found
        check_version(
            mismatches, path, table, "gpui-component", entry, pins.component_version,
            "gpui-component",
        )
    check_lock(mismatches, "crates/gpui-image", "gpui-pre", pins.locked_pre)
    check_lock(mismatches, "crates/gpui-image", "gpui-fast", pins.locked_fast)


def check_compograph(pins: HostPins, mismatches: list[Mismatch]) -> None:
    path, manifest = manifest_of("crates/compograph")
    workspace_deps = manifest.get("workspace", {}).get("dependencies", {})
    gpui = workspace_deps.get("gpui", {})
    if not isinstance(gpui, dict) or gpui.get("package") != "gpui-pre":
        mismatches.append(Mismatch(where=str(path), detail="missing workspace dependency gpui (gpui-pre)"))
    else:
        check_exact_req(
            mismatches, path, "workspace.dependencies", "gpui", gpui, "version", pins.pre_req,
            "the gpui-pre snapshot",
        )
    platform = workspace_deps.get("gpui_platform", {})
    if not isinstance(platform, dict) or platform.get("package") != "gpui-pre-platform":
        mismatches.append(
            Mismatch(where=str(path), detail="missing workspace dependency gpui_platform (gpui-pre-platform)")
        )
    else:
        check_exact_req(
            mismatches, path, "workspace.dependencies", "gpui_platform", platform, "version",
            pins.platform_req, "the gpui-pre-platform snapshot",
        )
        if sorted(platform.get("features", [])) != sorted(pins.platform_features):
            mismatches.append(
                Mismatch(
                    where=f"{path.relative_to(ROOT)} [workspace.dependencies] gpui_platform",
                    detail=(
                        f"enables {sorted(platform.get('features', []))} but the host "
                        f"enables {sorted(pins.platform_features)}; keep the desktop "
                        f"backends identical so both workspaces build against one GPUI"
                    ),
                )
            )
    check_lock(mismatches, "crates/compograph", "gpui-pre", pins.locked_pre)


def apply_fix(target: tuple[Path, str, str, str, str, str | None]) -> bool:
    """Replace one dependency field value inside its inline table, keeping formatting."""
    path, key, field, old, new, scope = target
    display = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    if field == "features":
        print(f"::error file={display}::automatic fix of {key} features is not supported; edit it by hand")
        return False
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    needle = f'{field} = "{old}"'
    lo, hi = 0, len(lines)
    if scope is not None:
        # Restrict the search to the dependency's own table: the same key may
        # repeat under several `[target.…]` sections, and may also name a
        # feature (`gpui = ["dep:gpui"]`).
        header = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip().startswith("[")
                and line.strip().strip("[]").replace("'", "") == scope
            ),
            None,
        )
        if header is None:
            print(f"::error file={display}::cannot find [{scope}] to fix {key}")
            return False
        lo = header + 1
        end_of_section = next(
            (index for index in range(lo, len(lines)) if lines[index].strip().startswith("[")),
            len(lines),
        )
        hi = end_of_section
    candidate = None
    for index in range(lo, hi):
        line = lines[index]
        if not re.match(rf"\s*{re.escape(key)}\s*=", line):
            continue
        depth = 0
        end = index
        for scan in range(index, hi):
            depth += lines[scan].count("{") + lines[scan].count("[")
            depth -= lines[scan].count("}") + lines[scan].count("]")
            if depth == 0 and (lines[scan].count("{") > 0 or scan == index):
                end = scan
                break
        else:
            continue
        if needle in "".join(lines[index : end + 1]):
            if candidate is not None:
                print(f"::error file={display}::{key} {needle} is ambiguous; fix it by hand")
                return False
            candidate = (index, end)
    if candidate is None:
        print(f"::error file={display}::{key}: expected {needle} but it moved; fix it by hand")
        return False
    start, end = candidate
    span = "".join(lines[start : end + 1])
    lines[start : end + 1] = [span.replace(needle, f'{field} = "{new}"', 1)]
    path.write_text("".join(lines))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check submodule GPUI backend pins against the host.")
    parser.add_argument("--fix", action="store_true", help="rewrite stale pins in place")
    args = parser.parse_args()

    pins = read_host()
    print(f"host gpui-pre snapshot : {pins.pre_req} (locked {pins.locked_pre})")
    print(f"host gpui-fast snapshot : {pins.fast_version} (locked {pins.locked_fast})")
    print(f"host zed revision      : {pins.zed_rev}")

    mismatches: list[Mismatch] = []
    check_tray(pins, mismatches)
    check_upstream_flavors(pins, mismatches, "crates/autostart")
    check_upstream_flavors(pins, mismatches, "crates/global-hotkey")
    check_image(pins, mismatches)
    check_compograph(pins, mismatches)

    if not mismatches:
        print("every submodule pins the host GPUI backend")
        return 0
    if args.fix:
        unfixable = [mismatch for mismatch in mismatches if mismatch.fix is None]
        for mismatch in unfixable:
            print(f"::error file={mismatch.where}::{mismatch.detail}")
        fixable = [mismatch.fix for mismatch in mismatches if mismatch.fix is not None]
        results = [apply_fix(target) for target in fixable if target is not None]
        ok = all(results)
        if ok and fixable:
            print(f"rewrote {len(fixable)} stale pin(s); re-run without --fix to verify")
        if unfixable:
            print("some mismatches need a lockfile update or a manual edit; see above")
        return 1
    for mismatch in mismatches:
        print(f"::error file={mismatch.where}::{mismatch.detail}")
    print(f"\n{len(mismatches)} submodule pin(s) drifted from the host; re-run with --fix")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
