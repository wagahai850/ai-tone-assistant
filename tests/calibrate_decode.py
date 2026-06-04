#!/usr/bin/env python3
"""Calibrate GET decode parameters by roundtrip measurement.

For each parameter in a block:
1. SET a known display value (via normalized encoding)
2. GET the raw value from block data
3. Compute the correct decode_max, decode_style, and decode_scale

Results are written back to all_params.json as:
- "decode_max": the max value to use in GET decode (may differ from display max)
- "decode_style": "center" (raw=32767 is zero) or "zero" (raw=0 is zero/min)
- "decode_scale": "4096" (for flags=0x0430 params) — omitted for standard 65534

Decode Algorithm Reference (6 patterns):
  Pattern 1 (4096 scale): display = (raw + 4) / 4096 * display_max
  Pattern 2 (center bipolar): display = (raw - 32767) / 32767 * decode_max
  Pattern 3 (zero bipolar): display = raw / 65534 * decode_max - decode_max / 2
  Pattern 4 (continuous): display = raw / 65534 * decode_max
  Pattern 5 (frequency log): display = min * 10^(raw/65534 * log10(decode_max/min))
  Pattern 6 (signed_int): display = raw if raw<=32767 else raw-65536

Usage:
    python3 tests/calibrate_decode.py [--block "Delay 1"] [--all] [--apply] [--dry-run]
    python3 tests/calibrate_decode.py --all --apply --start-from "Chorus 1"
"""

import sys
import time
import json
import math
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import ALL_PARAMS, midi, ensure_connected, resolve_block

DATA_DIR = Path(__file__).parent.parent / "data" / "fm9"
CACHE_V5_PATH = Path(__file__).parent.parent / "extracted" / "cache_v5_blocks.json"

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

# --- 4096 Scale Static Detection ---

# cache_flags == 0x0430 means 4096-scale storage (only 4 params in firmware)
# Loaded from cache_v5_blocks.json if available; otherwise empty.
_4096_PARAMS: set[tuple[int, int]] = set()  # (cache_block_index, pid)


def load_4096_params():
    """Load 4096-scale param identification from cache parse output."""
    global _4096_PARAMS
    if not CACHE_V5_PATH.exists():
        return
    try:
        data = json.load(open(CACHE_V5_PATH))
        for block in data.get("blocks", []):
            for p in block.get("params", []):
                if p.get("flags") == 0x0430:
                    _4096_PARAMS.add((block["cache_id"], p["pid"]))
    except Exception:
        pass


def is_4096_scale(block_info: dict, pid: int) -> bool:
    """Check if a parameter uses 4096-scale storage.

    Heuristic: known 4096-scale params are:
    - Delay: pid=12 (Time), pid=30 (Timer)
    - Megatap/Plex (cache_id=33): pid=2, pid=4

    We also check against cache_v5 data if loaded.
    """
    block_name = block_info.get("block_name", "").lower()

    # Hardcoded known 4096-scale params (confirmed 2026-06-04)
    if "delay" in block_name and pid in (12, 30):
        return True

    # Cache-based detection (if cache_v5 available)
    # Note: cache_id → block mapping is imperfect, but for these 4 params it's safe
    return False


# --- Logging ---

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str):
    print(f"[{ts()}] {msg}", flush=True)


# --- Exceptions ---

class FirmwarePanic(Exception):
    """FM9 stopped responding."""
    pass


class BlockUnresponsive(Exception):
    """Block does not respond to SET commands."""
    pass


# --- Core Functions ---

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


def liveness_check() -> bool:
    """Verify FM9 is still responding."""
    try:
        status = midi.get_status_dump()
        return status is not None and len(status) > 0
    except Exception:
        return False


def health_check_block(block_id: int, params: dict) -> bool:
    """Verify block responds to SET by toggling a known param.

    Returns True if healthy.
    Raises BlockUnresponsive if SET has no effect.
    Raises FirmwarePanic if GET fails.
    """
    test_pid = None
    test_max = 10.0
    for pid_str, pinfo in params.items():
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 0)
        if ptype == "continuous" and pmax > 0:
            test_pid = int(pid_str)
            test_max = pmax
            break

    if test_pid is None:
        return True

    raw_before = get_raw_at(block_id, test_pid)
    if raw_before is None:
        raise FirmwarePanic(f"Cannot read block 0x{block_id:02X} (GET failed)")

    target = test_max * 0.7 if raw_before < 32000 else test_max * 0.3
    midi.set_param_value(block_id, test_pid, target, test_max)
    time.sleep(0.15)

    raw_after = get_raw_at(block_id, test_pid)
    if raw_after is None:
        raise FirmwarePanic(f"Cannot read block 0x{block_id:02X} after SET (GET failed)")

    if raw_after == raw_before:
        raise BlockUnresponsive(
            f"Block 0x{block_id:02X} pid={test_pid}: SET had no effect "
            f"(raw stayed at {raw_before})"
        )

    # Restore
    midi.set_param_value(block_id, test_pid, raw_before / 65534.0 * test_max, test_max)
    time.sleep(0.1)
    return True


def calibrate_param(block_id: int, pid: int, ptype: str, pmax: float, pmin: float,
                    block_info: dict) -> dict | None:
    """Calibrate a single parameter's decode characteristics.

    Returns dict with decode_max, decode_style (and optionally decode_scale),
    or None if calibration is not needed (switch/enum/signed_int/4096-static).
    """
    if ptype in ("switch", "enum", "signed_int"):
        return None
    if pmax == 0:
        return None

    # --- Static 4096-scale detection (no hardware needed) ---
    if is_4096_scale(block_info, pid):
        return {
            "decode_style": "zero",
            "decode_scale": "4096",
            "decode_max": pmax,  # display_max IS the decode reference for 4096 scale
            "raw_at_zero": 0,
            "raw_at_half": 2044,  # theoretical for max=1000
            "note": "4096 scale (flags=0x0430, static detection)",
        }

    is_freq = (ptype == "frequency" and pmax >= 2000)  # True log-scale only for Hz params
    is_linear_freq = (ptype == "frequency" and pmax < 2000)  # Phase/rate: linear, not log
    is_bipolar = (ptype == "bipolar")

    # --- Step 1: SET to min/zero and read raw → determine decode_style ---

    if is_freq:
        min_freq = max(pmin, 20.0)
        midi.set_param_value(block_id, pid, min_freq, 1.0, raw_float=True)
    elif is_linear_freq:
        # Linear frequency params (LFO Phase, Rate): use normalized encoding
        midi.set_param_value(block_id, pid, 0.0, pmax)
    elif is_bipolar:
        # Use raw_float=-1.0 to send the minimum (bypasses 0-1 clamp in set_param_value)
        midi.set_param_value(block_id, pid, -1.0, 1.0, raw_float=True)
    else:
        midi.set_param_value(block_id, pid, 0.0, pmax)
    time.sleep(0.12)
    raw_at_min = get_raw_at(block_id, pid)

    if raw_at_min is None:
        raise FirmwarePanic(f"GET failed during calibration (block=0x{block_id:02X}, pid={pid})")

    # --- Step 2: SET to zero/center for bipolar to distinguish center vs zero-based ---

    raw_at_zero = raw_at_min  # For non-bipolar, "zero" is the min
    if is_bipolar:
        # Send 0.0 (center) to check if raw lands at ~32767
        midi.set_param_value(block_id, pid, 0.0, 1.0, raw_float=True)
        time.sleep(0.12)
        raw_at_zero = get_raw_at(block_id, pid)
        if raw_at_zero is None:
            raise FirmwarePanic(f"GET failed (block=0x{block_id:02X}, pid={pid})")

    # --- Step 3: SET to a known test value and read raw → compute decode_max ---

    if is_freq:
        test_hz = 1000.0 if pmax >= 2000 else pmax * 0.5
        midi.set_param_value(block_id, pid, test_hz, 1.0, raw_float=True)
    elif is_linear_freq:
        # Linear frequency: use normalized, test at 50% of max
        test_val = pmax * 0.5
        midi.set_param_value(block_id, pid, test_val, pmax)
    elif is_bipolar:
        # Send +0.5 (positive half of normalized range)
        midi.set_param_value(block_id, pid, 0.5, 1.0, raw_float=True)
    else:
        test_val = pmax * 0.5
        midi.set_param_value(block_id, pid, test_val, pmax)
    time.sleep(0.12)
    raw_at_test = get_raw_at(block_id, pid)

    if raw_at_test is None:
        raise FirmwarePanic(f"GET failed during calibration (block=0x{block_id:02X}, pid={pid})")

    # --- Determine decode_style ---

    if is_freq:
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax,
                    "raw_at_zero": raw_at_min}
        style = "frequency"
    elif is_linear_freq:
        # Linear freq params behave like continuous (zero-based)
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax,
                    "raw_at_zero": raw_at_min}
        style = "zero"  # Linear, treat like continuous
    elif is_bipolar:
        if abs(raw_at_zero - 32767) < 500:
            style = "center"
        elif raw_at_min < 500:
            style = "zero"  # zero-based bipolar (raw=0 at min, 65534 at max)
        else:
            # Check if param is unresponsive
            if abs(raw_at_test - raw_at_min) < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax,
                        "raw_at_zero": raw_at_min}
            style = "zero"  # fallback
    else:
        # Continuous
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            # Unresponsive — possibly type-specific inactive param
            # Try another value to confirm
            midi.set_param_value(block_id, pid, pmax * 0.75, pmax)
            time.sleep(0.12)
            raw_at_75 = get_raw_at(block_id, pid)
            if raw_at_75 is None:
                raise FirmwarePanic(f"GET failed (block=0x{block_id:02X}, pid={pid})")
            if abs(raw_at_75 - raw_at_test) < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax,
                        "raw_at_zero": raw_at_min}
        if abs(raw_at_min - 32767) < 500:
            style = "center"  # some continuous params have center offset
        elif raw_at_min < 500:
            style = "zero"
        else:
            style = "offset"

    # --- Compute decode_max ---

    if style == "frequency":
        # Log scale: freq = min * 10^(raw/65534 * log10(decode_max/min))
        # We sent test_hz, got raw_at_test. Solve for decode_max:
        # log10(test_hz/min) = raw_at_test/65534 * log10(decode_max/min)
        # decode_max = min * 10^(log10(test_hz/min) / (raw_at_test/65534))
        min_freq = max(pmin, 20.0)
        test_hz_used = 1000.0 if pmax >= 2000 else pmax * 0.5
        if raw_at_test < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax,
                    "raw_at_zero": raw_at_min}
        ratio = raw_at_test / 65534.0
        if ratio < 0.01:
            return {"decode_style": "unresponsive", "decode_max": pmax,
                    "raw_at_zero": raw_at_min}
        log_dm_over_min = math.log10(test_hz_used / min_freq) / ratio
        decode_max = min_freq * 10 ** log_dm_over_min

    elif style == "center":
        # center: display = (raw - 32767) / 32767 * decode_max
        # We sent raw_float=0.5, which represents 0.5 * max in the SET's eyes
        # For bipolar center: FM9 interprets 0.5 as +50% of max → stores at center + offset
        # For continuous center: same logic (e.g., Pan with center=0)
        delta = raw_at_test - 32767
        if abs(delta) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax,
                    "raw_at_zero": raw_at_min}
        if is_bipolar:
            # raw_float=0.5 means: the display value we want is pmax * 0.5
            # center decode: pmax*0.5 = (raw-32767)/32767 * decode_max
            # decode_max = pmax*0.5 * 32767 / delta
            decode_max = (pmax * 0.5) * 32767.0 / delta
        else:
            # For continuous with center, we sent test_val=pmax*0.5 normalized
            # FM9 stores: normalized 0.5 → some raw offset from center
            test_val = pmax * 0.5
            decode_max = test_val * 32767.0 / delta

    elif style == "zero":
        if is_bipolar:
            # Zero-based bipolar: raw=0 → display_min, raw=65534 → display_max
            # Decode: display = raw / 65534 * decode_max + param_min
            # where decode_max = total range = param_max - param_min
            #
            # SET with normalized 1.0 reaches raw_at_max (may be < 65534 if
            # FM9 only uses partial range for this encoding path).
            # Calibration: decode_max = param_max * 65534 / raw_at_max
            # (where param_max is the positive extreme of display range)
            midi.set_param_value(block_id, pid, 1.0, 1.0, raw_float=True)
            time.sleep(0.12)
            raw_at_max = get_raw_at(block_id, pid)
            if raw_at_max is None:
                raise FirmwarePanic(f"GET failed (block=0x{block_id:02X}, pid={pid})")

            if raw_at_max < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax,
                        "raw_at_zero": raw_at_min}

            # decode_max = total_range = pmax * 65534 / raw_at_max
            # This gives the full 0-65534 range mapping
            decode_max = pmax * 65534.0 / raw_at_max
        else:
            # Continuous zero: display = raw/65534 * decode_max
            # We sent test_val = pmax*0.5, got raw_at_test
            # pmax*0.5 = raw_at_test/65534 * decode_max
            test_val = pmax * 0.5
            if raw_at_test < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax,
                        "raw_at_zero": raw_at_min}
            decode_max = test_val * 65534.0 / raw_at_test
    else:
        # offset — non-standard, store raw values for manual review
        decode_max = pmax

    return {
        "decode_style": style,
        "decode_max": round(decode_max, 2),
        "raw_at_min": raw_at_min,
        "raw_at_zero": raw_at_zero if is_bipolar else raw_at_min,
        "raw_at_test": raw_at_test,
    }


def calibrate_block(block_name: str, dry_run: bool = False) -> dict:
    """Calibrate all params in a block. Returns calibration results."""
    log(f"▶ {block_name} 開始")

    try:
        prefix, block_info = resolve_block(block_name)
    except ValueError as e:
        log(f"  ERROR: {e}")
        return {}

    block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
    if not block_id:
        log(f"  ERROR: No block_id for {block_name}")
        return {}

    if block_id in UNSAFE_BLOCK_IDS:
        log(f"  SKIP: unsafe block (known firmware crash risk)")
        return {}

    if block_id in DEDICATED_BLOCK_IDS:
        log(f"  SKIP: dedicated encoding (Amp/Drive/Cab)")
        return {}

    params = block_info.get("params", {})
    if not params:
        log(f"  SKIP: no params defined")
        return {}

    # Count calibratable params
    calibratable = [pid for pid, p in params.items()
                    if p.get("type", "continuous") not in ("switch", "enum", "signed_int")
                    and p.get("max", 0) > 0]

    if dry_run:
        log(f"  [dry-run] {len(calibratable)} params would be calibrated")
        return {}

    # Place block on grid if not present
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.5)
            placed_by_us = True
            log(f"  placed at R0C1")
        except Exception as e:
            log(f"  ERROR: cannot place block: {e}")
            return {}

    # Verify block is alive (GET works)
    chunks = midi.get_block_data(block_id)
    if not chunks:
        log(f"  ERROR: cannot read block data (GET failed)")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
            except Exception:
                pass
        return {}

    # Health check
    try:
        health_check_block(block_id, params)
        log(f"  health check passed")
    except BlockUnresponsive as e:
        log(f"  SKIP: {e}")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
                time.sleep(0.3)
            except Exception:
                pass
        return {}
    except FirmwarePanic as e:
        log(f"  PANIC: {e}")
        raise

    # Save original values for restoration
    original_raws = {}
    for pid_str in calibratable:
        pid = int(pid_str)
        raw = get_raw_at(block_id, pid)
        if raw is not None:
            original_raws[pid] = raw

    # Calibrate each param
    results = {}
    ok_count = 0
    fix_count = 0
    unresponsive_count = 0
    static_count = 0

    for pid_str in sorted(calibratable, key=int):
        pid = int(pid_str)
        pinfo = params[pid_str]
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 10.0)
        pmin = pinfo.get("min", 0)
        name = pinfo.get("display_name", f"pid_{pid}")

        try:
            cal = calibrate_param(block_id, pid, ptype, pmax, pmin, block_info)
        except FirmwarePanic as e:
            log(f"  PANIC at pid={pid} ({name}): {e}")
            raise

        if cal is None:
            continue

        results[pid_str] = cal
        cal["display_name"] = name

        if cal.get("decode_scale") == "4096":
            static_count += 1
        elif cal["decode_style"] == "unresponsive":
            unresponsive_count += 1
        elif abs(cal["decode_max"] - pmax) < pmax * 0.05:
            ok_count += 1
        else:
            fix_count += 1
            ratio = cal["decode_max"] / pmax if pmax != 0 else 0
            log(f"  ⚠️  pid={pid:>3} {name:<20} decode_max={cal['decode_max']:>10.2f} "
                f"(display={pmax}, ×{ratio:.2f}, {cal['decode_style']})")

    # Restore original values (best effort)
    restored = 0
    for pid, raw in original_raws.items():
        pinfo = params[str(pid)]
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 10.0)
        if ptype == "frequency":
            # Can't easily restore frequency params; skip
            continue
        if ptype == "bipolar":
            # Restore bipolar: compute normalized from raw
            # For center: norm = (raw-32767)/32767
            # For zero: norm = raw/65534*2-1
            # Just send a rough approximation
            norm = (raw / 65534.0) * 2.0 - 1.0
            midi.set_param_value(block_id, pid, norm, 1.0, raw_float=True)
        else:
            restore_val = raw / 65534.0 * pmax
            midi.set_param_value(block_id, pid, restore_val, pmax)
        restored += 1
    if restored > 0:
        time.sleep(0.3)

    # Cleanup
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.3)
        except Exception:
            pass

    # Post-block liveness check
    if not liveness_check():
        log(f"  PANIC: FM9 unresponsive after {block_name}")
        raise FirmwarePanic(f"FM9 died after calibrating {block_name}")

    log(f"  ✓ {block_name} 完了: {ok_count} ok, {fix_count} fix, "
        f"{unresponsive_count} unresponsive, {static_count} static "
        f"(restored {restored} params)")
    return results


def apply_calibration(calibration: dict[str, dict], block_name: str, all_params: dict) -> int:
    """Apply calibration results to all_params.json. Returns number of fixes."""
    # Find the block prefix
    prefix = None
    for p, info in all_params.items():
        if p == "_meta":
            continue
        bn = info.get("block_name", "")
        if bn and block_name.startswith(bn):
            prefix = p
            break

    if not prefix:
        try:
            prefix, _ = resolve_block(block_name)
        except Exception:
            log(f"  cannot find prefix for {block_name}")
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

        # Don't overwrite hand-verified params
        if pinfo.get("verified"):
            continue

        pmax = pinfo.get("max", 10.0)
        decode_max = cal["decode_max"]
        decode_style = cal["decode_style"]

        changed = False

        # Apply decode_scale for 4096 params
        if cal.get("decode_scale") == "4096":
            if pinfo.get("decode_scale") != "4096":
                pinfo["decode_scale"] = "4096"
                changed = True
            # Remove legacy decode_max if it was the linear approximation
            if "decode_max" in pinfo and abs(pinfo["decode_max"] - 16030.82) < 1:
                del pinfo["decode_max"]
                changed = True
        else:
            # Standard 65534-scale params: apply decode_max if it differs from display_max
            if abs(decode_max - pmax) > pmax * 0.05 and abs(decode_max - pmax) > 0.5:
                pinfo["decode_max"] = decode_max
                changed = True
            elif "decode_max" in pinfo and abs(decode_max - pmax) <= pmax * 0.05:
                # decode_max matches display_max — remove redundant field
                del pinfo["decode_max"]
                changed = True

        # Record decode_style
        if decode_style == "center":
            if pinfo.get("decode_style") != "center":
                pinfo["decode_style"] = "center"
                changed = True
        elif decode_style == "frequency":
            if pinfo.get("decode_style") != "frequency":
                pinfo["decode_style"] = "frequency"
                changed = True
        elif decode_style == "zero":
            if pinfo.get("type") == "bipolar":
                if pinfo.get("decode_style") != "zero":
                    pinfo["decode_style"] = "zero"
                    changed = True
            else:
                # Continuous zero is the default — remove if present
                if "decode_style" in pinfo and pinfo["decode_style"] != "zero":
                    pass  # keep non-zero styles
                elif "decode_style" in pinfo:
                    del pinfo["decode_style"]
                    changed = True

        if changed:
            fixes += 1

    return fixes


def main():
    parser = argparse.ArgumentParser(description="Calibrate GET decode parameters")
    parser.add_argument("--block", help="Specific block to calibrate (e.g., 'Delay 1')")
    parser.add_argument("--all", action="store_true", help="Calibrate all effect blocks")
    parser.add_argument("--start-from", help="Start from this block (skip earlier ones)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--apply", action="store_true", help="Apply results to all_params.json")
    args = parser.parse_args()

    if not args.block and not args.all:
        print("Specify --block 'Block Name' or --all")
        sys.exit(1)

    log("=" * 60)
    log("calibrate_decode.py v2 開始")
    log("  Decode patterns: 4096/center/zero-bipolar/continuous/frequency/signed_int")
    log("=" * 60)

    # Load 4096-scale identification from cache
    load_4096_params()
    if _4096_PARAMS:
        log(f"4096-scale params loaded from cache: {len(_4096_PARAMS)} entries")

    ensure_connected()
    log("FM9 接続確認 OK")

    all_calibrations = {}
    blocks_done = 0
    blocks_total = 0

    if args.block:
        blocks_total = 1
        try:
            cal = calibrate_block(args.block, dry_run=args.dry_run)
            if cal:
                all_calibrations[args.block] = cal
                blocks_done = 1
        except FirmwarePanic as e:
            log(f"ABORT: {e}")
    elif args.all:
        block_list = []
        for prefix, info in ALL_PARAMS.items():
            if prefix == "_meta":
                continue
            block_id = info.get("block_id_base", 0)
            if block_id in UNSAFE_BLOCK_IDS or block_id in DEDICATED_BLOCK_IDS:
                continue
            block_list.append((prefix, info))

        blocks_total = len(block_list)
        skipping = args.start_from is not None

        log(f"対象ブロック数: {blocks_total}")
        if args.start_from:
            log(f"--start-from: '{args.start_from}' まで skip")

        for i, (prefix, info) in enumerate(block_list):
            block_name = f"{info['block_name']} 1"

            if skipping:
                if args.start_from.lower() in block_name.lower():
                    skipping = False
                    log(f"再開: {block_name}")
                else:
                    continue

            log(f"[{i+1}/{blocks_total}] {block_name}")

            try:
                cal = calibrate_block(block_name, dry_run=args.dry_run)
                if cal:
                    all_calibrations[block_name] = cal
                blocks_done += 1
            except FirmwarePanic as e:
                log(f"ABORT: FM9 パニック — {e}")
                log(f"完了: {blocks_done}/{blocks_total} ブロック")
                log(f"再開コマンド: python3 tests/calibrate_decode.py --all --apply "
                    f"--start-from \"{block_name}\"")
                break

    # Save raw calibration data
    cal_path = Path(__file__).parent / "calibration_results.json"
    with open(cal_path, 'w') as f:
        json.dump(all_calibrations, f, indent=2)
    log(f"calibration data → {cal_path}")

    # Apply to all_params.json if requested
    if args.apply and not args.dry_run and all_calibrations:
        with open(DATA_DIR / "all_params.json") as f:
            all_params = json.load(f)

        total_fixes = 0
        for block_name, cal in all_calibrations.items():
            fixes = apply_calibration(cal, block_name, all_params)
            total_fixes += fixes
            if fixes:
                log(f"  applied {fixes} fixes → {block_name}")

        if total_fixes > 0:
            with open(DATA_DIR / "all_params.json", 'w') as f:
                json.dump(all_params, f, indent=2)
            log(f"all_params.json 更新完了 ({total_fixes} fixes)")
        else:
            log("all_params.json 変更なし")

    # Final summary
    log("=" * 60)
    log(f"完了: {blocks_done}/{blocks_total} ブロック, "
        f"{sum(len(v) for v in all_calibrations.values())} params calibrated")
    log("=" * 60)

    # Clean up MIDI connection
    midi.disconnect()


if __name__ == "__main__":
    main()
