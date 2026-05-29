#!/usr/bin/env python3
"""Calibrate GET decode parameters by roundtrip measurement.

For each parameter in a block:
1. SET a known display value (via normalized encoding)
2. GET the raw value from block data
3. Compute the correct decode_max and encoding style

Results are written back to all_params.json as:
- "decode_max": the max value to use in GET decode (may differ from display max)
- "decode_style": "center" (raw=32767 is zero) or "zero" (raw=0 is zero/min)

Usage:
    python3 tests/calibrate_decode.py [--block "Delay 1"] [--all] [--dry-run]
"""

import sys
import time
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import ALL_PARAMS, midi, ensure_connected, resolve_block

DATA_DIR = Path(__file__).parent.parent / "data" / "fm9"

# Blocks that are known to crash firmware — skip
UNSAFE_BLOCK_IDS = {
    0x86, 0x8A, 0x8E, 0x96, 0x9A, 0x9E, 0xA2, 0xA6, 0xB2,
}

# Amp/Drive/Cab have dedicated encoding — skip
DEDICATED_BLOCK_IDS = {
    0x3A, 0x3B, 0x3C, 0x3D,  # Amp 1-4
    0x76, 0x77, 0x78, 0x79,  # Drive 1-4
    0x3E, 0x3F, 0x40, 0x41,  # Cab 1-4
}


def get_raw_at(block_id: int, pid: int) -> int | None:
    """Read raw value at pid from block data (channel A)."""
    chunks = midi.get_block_data(block_id)
    if not chunks:
        return None
    combined = list(chunks[0])
    for c in chunks[1:]:
        combined.extend(c[7:])
    offset = 7 + pid * 3
    if offset + 2 >= len(combined):
        return None
    lo, hi, msb = combined[offset], combined[offset + 1], combined[offset + 2]
    return lo | (hi << 7) | (msb << 14)


def calibrate_param(block_id: int, pid: int, ptype: str, pmax: float, pmin: float) -> dict | None:
    """Calibrate a single parameter's decode characteristics.

    Returns dict with decode_max and decode_style, or None if calibration failed.
    """
    if ptype in ("switch", "enum", "signed_int"):
        return None
    if pmax == 0:
        return None

    # Step 1: SET to 0 (center/min) and read raw → determines encoding style
    midi.set_param_value(block_id, pid, 0.0, pmax)
    time.sleep(0.12)
    raw_at_zero = get_raw_at(block_id, pid)

    if raw_at_zero is None:
        return None

    # Step 2: SET to 50% of max and read raw → determines decode_max
    test_val = pmax * 0.5
    midi.set_param_value(block_id, pid, test_val, pmax)
    time.sleep(0.12)
    raw_at_half = get_raw_at(block_id, pid)

    if raw_at_half is None:
        return None

    # Determine encoding style
    if abs(raw_at_zero - 32767) < 500:
        style = "center"  # raw=32767 is the zero point (true bipolar)
    elif raw_at_zero < 500:
        style = "zero"    # raw=0 is the zero/min point
    else:
        # Param didn't respond to SET (e.g., Level, or type-specific inactive)
        # Try a second test value to confirm
        test_val2 = pmax * 0.75
        midi.set_param_value(block_id, pid, test_val2, pmax)
        time.sleep(0.12)
        raw_at_75 = get_raw_at(block_id, pid)
        if raw_at_75 == raw_at_half:
            # Param is unresponsive — likely inactive for current type
            return {"decode_style": "unresponsive", "decode_max": pmax, "raw_at_zero": raw_at_zero}
        # Responsive but non-standard zero point
        style = "offset"

    # Compute decode_max from raw_at_half
    if style == "center":
        # For center-offset: val = (raw - 32767) / 32767 * decode_max
        # We sent test_val = pmax * 0.5, so:
        # pmax * 0.5 = (raw_at_half - 32767) / 32767 * decode_max
        delta = raw_at_half - 32767
        if abs(delta) < 10:
            # raw didn't move from center — param unresponsive
            return {"decode_style": "unresponsive", "decode_max": pmax, "raw_at_zero": raw_at_zero}
        decode_max = (pmax * 0.5) * 32767.0 / delta
    elif style == "zero":
        # For zero-based: val = raw / 65534 * decode_max
        # We sent test_val = pmax * 0.5, so:
        # pmax * 0.5 = raw_at_half / 65534 * decode_max
        if raw_at_half < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax, "raw_at_zero": raw_at_zero}
        decode_max = (pmax * 0.5) * 65534.0 / raw_at_half
    else:
        # offset style — use the two measurements to compute
        # This is complex; store raw values for manual analysis
        decode_max = pmax  # fallback

    return {
        "decode_style": style,
        "decode_max": round(decode_max, 2),
        "raw_at_zero": raw_at_zero,
        "raw_at_half": raw_at_half,
    }


def calibrate_block(block_name: str, dry_run: bool = False) -> dict:
    """Calibrate all params in a block. Returns calibration results."""
    print(f"\n{'='*60}")
    print(f"Calibrating: {block_name}")
    print(f"{'='*60}")

    try:
        prefix, block_info = resolve_block(block_name)
    except ValueError as e:
        print(f"  ERROR: {e}")
        return {}

    block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
    if not block_id:
        print(f"  ERROR: No block_id for {block_name}")
        return {}

    if block_id in UNSAFE_BLOCK_IDS:
        print(f"  SKIP: Unsafe block (known to crash firmware)")
        return {}

    if block_id in DEDICATED_BLOCK_IDS:
        print(f"  SKIP: Dedicated encoding (Amp/Drive/Cab)")
        return {}

    # Ensure block is on grid
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.5)
            placed_by_us = True
            print(f"  Placed {block_name} at R0C1")
        except Exception as e:
            print(f"  ERROR: Cannot place block: {e}")
            return {}

    # Verify block is alive
    chunks = midi.get_block_data(block_id)
    if not chunks:
        print(f"  ERROR: Cannot read block data")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
            except Exception:
                pass
        return {}

    params = block_info.get("params", {})
    results = {}
    ok_count = 0
    fail_count = 0
    unresponsive_count = 0

    if dry_run:
        for pid_str, pinfo in sorted(params.items(), key=lambda x: int(x[0])):
            ptype = pinfo.get("type", "continuous")
            if ptype in ("switch", "enum", "signed_int"):
                continue
            print(f"  [dry-run] Would calibrate: pid={pid_str} {pinfo['display_name']}")
        if placed_by_us:
            midi.delete_block_at(row=0, col=1)
        return {}

    for pid_str, pinfo in sorted(params.items(), key=lambda x: int(x[0])):
        pid = int(pid_str)
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 10.0)
        pmin = pinfo.get("min", 0)
        name = pinfo.get("display_name", f"pid_{pid}")

        if ptype in ("switch", "enum", "signed_int"):
            continue

        cal = calibrate_param(block_id, pid, ptype, pmax, pmin)
        if cal is None:
            continue

        results[pid_str] = cal
        cal["display_name"] = name

        if cal["decode_style"] == "unresponsive":
            unresponsive_count += 1
        elif abs(cal["decode_max"] - pmax) < pmax * 0.05:
            ok_count += 1
        else:
            fail_count += 1
            ratio = cal["decode_max"] / pmax if pmax != 0 else 0
            print(f"  ⚠️  pid={pid:>3} {name:>14}: decode_max={cal['decode_max']:>10.2f} "
                  f"(display_max={pmax}, ratio={ratio:.2f}, style={cal['decode_style']})")

    # Cleanup
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.3)
        except Exception:
            pass

    print(f"  Summary: {ok_count} ok, {fail_count} need fix, {unresponsive_count} unresponsive")
    return results


def apply_calibration(calibration: dict[str, dict], block_name: str, all_params: dict) -> int:
    """Apply calibration results to all_params.json. Returns number of fixes."""
    # Find the block prefix
    prefix = None
    for p, info in all_params.items():
        if p == "_meta":
            continue
        if info.get("block_name") == block_name.replace(" 1", "").replace(" 2", ""):
            prefix = p
            break
        # Try with instance number stripped
        bn = info.get("block_name", "")
        if bn and block_name.startswith(bn):
            prefix = p
            break

    if not prefix:
        # Try resolve
        try:
            from tools import resolve_block
            prefix, _ = resolve_block(block_name)
        except Exception:
            print(f"  Cannot find prefix for {block_name}")
            return 0

    block_data = all_params.get(prefix)
    if not block_data:
        return 0

    fixes = 0
    for pid_str, cal in calibration.items():
        if cal["decode_style"] == "unresponsive":
            continue

        pinfo = block_data.get("params", {}).get(pid_str)
        if not pinfo:
            continue

        pmax = pinfo.get("max", 10.0)
        decode_max = cal["decode_max"]

        # Only fix if decode_max differs significantly from display_max
        if abs(decode_max - pmax) > pmax * 0.05 and abs(decode_max - pmax) > 0.5:
            pinfo["decode_max"] = decode_max
            fixes += 1

        # Record decode_style if it's center (bipolar params that are truly center-offset)
        if cal["decode_style"] == "center":
            pinfo["decode_style"] = "center"
        elif cal["decode_style"] == "zero" and pinfo.get("type") == "bipolar":
            # Bipolar param stored as zero-based — record this
            pinfo["decode_style"] = "zero"

    return fixes


def main():
    parser = argparse.ArgumentParser(description="Calibrate GET decode parameters")
    parser.add_argument("--block", help="Specific block to calibrate (e.g., 'Delay 1')")
    parser.add_argument("--all", action="store_true", help="Calibrate all effect blocks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--apply", action="store_true", help="Apply results to all_params.json")
    args = parser.parse_args()

    if not args.block and not args.all:
        print("Specify --block 'Block Name' or --all")
        sys.exit(1)

    ensure_connected()
    print("Connected to FM9")

    all_calibrations = {}

    if args.block:
        cal = calibrate_block(args.block, dry_run=args.dry_run)
        if cal:
            all_calibrations[args.block] = cal
    elif args.all:
        # Iterate all effect blocks (skip Amp/Drive/Cab/unsafe)
        for prefix, info in ALL_PARAMS.items():
            if prefix == "_meta":
                continue
            block_id = info.get("block_id_base", 0)
            if block_id in UNSAFE_BLOCK_IDS or block_id in DEDICATED_BLOCK_IDS:
                continue
            block_name = f"{info['block_name']} 1"
            cal = calibrate_block(block_name, dry_run=args.dry_run)
            if cal:
                all_calibrations[block_name] = cal

            # Liveness check
            status = midi.get_status_dump()
            if status is None:
                print("\n!!! FM9 DIED. Aborting.")
                break

    # Save raw calibration data
    cal_path = Path(__file__).parent / "calibration_results.json"
    with open(cal_path, 'w') as f:
        json.dump(all_calibrations, f, indent=2)
    print(f"\nCalibration data saved to {cal_path}")

    # Apply to all_params.json if requested
    if args.apply and not args.dry_run:
        with open(DATA_DIR / "all_params.json") as f:
            all_params = json.load(f)

        total_fixes = 0
        for block_name, cal in all_calibrations.items():
            fixes = apply_calibration(cal, block_name, all_params)
            total_fixes += fixes
            if fixes:
                print(f"  Applied {fixes} fixes to {block_name}")

        if total_fixes > 0:
            with open(DATA_DIR / "all_params.json", 'w') as f:
                json.dump(all_params, f, indent=2)
            print(f"\nUpdated all_params.json ({total_fixes} total fixes)")
        else:
            print("\nNo fixes needed")


if __name__ == "__main__":
    main()
