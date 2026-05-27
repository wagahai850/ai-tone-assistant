#!/usr/bin/env python3
"""Round-trip test: SET → GET for all parameters on all blocks.

Requires FM9 connected via USB. Tests that the current encoding
assumptions are correct by verifying SET values can be read back.

Usage:
    python3 tests/test_roundtrip.py [--block "Amp 1"] [--dry-run]
"""

import sys
import time
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fractal_midi import FractalMidi

# Load parameter data
DATA_DIR = Path(__file__).parent.parent / "data" / "fm9"
with open(DATA_DIR / "all_params.json") as f:
    ALL_PARAMS = json.load(f)
with open(DATA_DIR / "blocks.json") as f:
    BLOCKS = json.load(f)


def get_test_value(meta: dict, current_value) -> float | None:
    """Pick a safe test value that's different from current."""
    param_type = meta.get("type", "continuous")
    param_max = meta.get("max", 10.0)
    param_min = meta.get("min", 0)

    if param_type == "enum":
        return None  # Skip enums (can change block behavior)

    if param_type == "switch":
        # Toggle
        return not current_value if isinstance(current_value, bool) else (0 if current_value else 1)

    if param_type == "signed_int":
        # Use a small value different from current
        if current_value == 0:
            return 1
        elif current_value > 0:
            return current_value - 1
        else:
            return current_value + 1

    if param_type == "bipolar":
        # Pick midpoint or offset from current
        mid = (param_max + param_min) / 2
        if abs(current_value - mid) > 0.5:
            return round(mid, 2)
        else:
            # Stay within range
            test = round(mid + 1.0, 2)
            return min(param_max, max(param_min, test))

    # continuous
    if param_max >= 20000:
        # Frequency param — pick a safe mid value
        return 1000.0
    mid = param_max * 0.5
    if abs(current_value - mid) > 0.1:
        return round(mid, 2)
    else:
        return round(mid + 0.5, 2)


def decode_value(raw: int, meta: dict) -> float:
    """Decode raw 3-byte value to display value (same logic as server)."""
    import math
    param_type = meta.get("type", "continuous")
    param_max = meta.get("max", 10.0)
    param_min = meta.get("min", 0)

    if param_type == "switch":
        return bool(raw & 0x7F)
    elif param_type == "enum":
        return raw
    elif param_type == "signed_int":
        return raw if raw <= 32767 else raw - 65536
    elif param_type == "bipolar":
        total_range = param_max - param_min
        return round(raw / 65534.0 * total_range + param_min, 2)
    elif param_max >= 20000:
        # Log frequency
        if raw == 0:
            return 20.0
        return round(20.0 * 10 ** (raw / 65534.0 * math.log10(param_max / 20.0)), 1)
    else:
        return round(raw / 65534.0 * param_max, 2)


def encode_and_set(midi: FractalMidi, block_id: int, pid: int, value, meta: dict,
                   is_amp_drive: bool) -> bool:
    """SET a parameter value using the correct encoding."""
    param_type = meta.get("type", "continuous")
    param_max = meta.get("max", 10.0)
    param_min = meta.get("min", 0)

    if param_type == "switch":
        midi.set_param_value(block_id, pid, 1.0 if value else 0.0, 1.0)
    elif param_type == "signed_int":
        midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
    elif param_type == "bipolar":
        if is_amp_drive:
            midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
        else:
            midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
    elif param_max >= 20000:
        # Frequency — always raw_float regardless of block type
        midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
    else:
        # Continuous
        if is_amp_drive:
            midi.set_param_value(block_id, pid, float(value), param_max)
        else:
            midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
    return True


def read_param(combined: list, pid: int, channel_offset: int) -> int:
    """Read raw 3-byte value from combined chunk data."""
    offset = 7 + pid * 3 + channel_offset
    if offset + 2 >= len(combined):
        return -1
    lo = combined[offset]
    hi = combined[offset + 1]
    msb = combined[offset + 2]
    return lo | (hi << 7) | (msb << 14)


def run_test(midi: FractalMidi, block_filter: str | None = None, dry_run: bool = False):
    """Run round-trip test on all blocks/params."""
    AMP_DRIVE_IDS = {0x3A, 0x3B, 0x3C, 0x3D, 0x76, 0x77, 0x78, 0x79}
    CAB_IDS = {0x3E, 0x3F, 0x40, 0x41}

    results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    for prefix, block_info in ALL_PARAMS.items():
        block_id_str = block_info.get("block_id")
        if not block_id_str:
            continue
        block_id = int(block_id_str, 16)
        block_name = block_info.get("block_name", prefix)

        # Filter
        if block_filter and block_filter.lower() not in block_name.lower():
            continue

        # Skip Cab (complex encoding, tested separately)
        if block_id in CAB_IDS:
            results["skip"] += len(block_info.get("params", {}))
            continue

        is_amp_drive = block_id in AMP_DRIVE_IDS

        print(f"\n{'='*60}")
        print(f"Block: {block_name} (0x{block_id:02X})")
        print(f"{'='*60}")

        # Place block at R0C1
        if not dry_run:
            try:
                midi.add_block_at(block_id, row=0, col=1)
                time.sleep(0.3)
            except Exception as e:
                print(f"  SKIP: Cannot place block: {e}")
                results["skip"] += len(block_info.get("params", {}))
                continue

        # Get block data (Channel A = default)
        channel_offset = 0
        if not dry_run:
            chunks = midi.get_block_data(block_id)
            if not chunks:
                print(f"  SKIP: Cannot read block data")
                results["skip"] += len(block_info.get("params", {}))
                # Clean up
                midi.delete_block_at(row=0, col=1)
                time.sleep(0.2)
                continue

            # Concatenate chunks
            combined = list(chunks[0])
            for c in chunks[1:]:
                combined.extend(c[7:])
            channel_stride = (len(combined) - 7) // 4
            # Always test Channel A (offset=0) since we just placed the block
        else:
            combined = []

        params = block_info.get("params", {})
        block_pass = 0
        block_fail = 0

        for pid_str, pinfo in params.items():
            pid = int(pid_str)
            meta = pinfo.get("meta", {})
            param_type = meta.get("type", "continuous")
            display_name = pinfo.get("display_name", f"pid_{pid}")

            # Skip enums
            if param_type == "enum":
                results["skip"] += 1
                continue

            if dry_run:
                results["skip"] += 1
                continue

            # Read current value
            raw_before = read_param(combined, pid, channel_offset)
            if raw_before < 0:
                results["skip"] += 1
                continue
            current_value = decode_value(raw_before, meta)

            # Pick test value
            test_value = get_test_value(meta, current_value)
            if test_value is None:
                results["skip"] += 1
                continue

            # SET test value
            try:
                encode_and_set(midi, block_id, pid, test_value, meta, is_amp_drive)
            except Exception as e:
                print(f"  FAIL {display_name}: SET error: {e}")
                results["fail"] += 1
                block_fail += 1
                results["errors"].append({"block": block_name, "param": display_name, "error": f"SET: {e}"})
                continue

            time.sleep(0.15)

            # GET and verify
            chunks2 = midi.get_block_data(block_id)
            if not chunks2:
                print(f"  FAIL {display_name}: Cannot read after SET")
                results["fail"] += 1
                block_fail += 1
                continue

            combined2 = list(chunks2[0])
            for c in chunks2[1:]:
                combined2.extend(c[7:])
            raw_after = read_param(combined2, pid, channel_offset)
            readback_value = decode_value(raw_after, meta)

            # Compare with tolerance
            if param_type == "switch":
                match = bool(readback_value) == bool(test_value)
            elif param_type == "signed_int":
                match = readback_value == test_value
            else:
                tolerance = 0.05 if meta.get("max", 10) < 100 else 0.5
                match = abs(readback_value - test_value) <= tolerance

            if match:
                results["pass"] += 1
                block_pass += 1
            else:
                print(f"  FAIL {display_name} (pid={pid}, {param_type}): "
                      f"sent={test_value}, got={readback_value} (raw={raw_after})")
                results["fail"] += 1
                block_fail += 1
                results["errors"].append({
                    "block": block_name, "param": display_name, "pid": pid,
                    "type": param_type, "sent": test_value, "got": readback_value,
                    "raw": raw_after,
                })

            # Restore original value
            try:
                encode_and_set(midi, block_id, pid, current_value, meta, is_amp_drive)
                time.sleep(0.05)
            except Exception:
                pass

        if not dry_run:
            print(f"  Result: {block_pass} pass, {block_fail} fail")
            # Remove block
            try:
                midi.delete_block_at(row=0, col=1)
                time.sleep(0.2)
            except Exception:
                pass

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {results['pass']} pass, {results['fail']} fail, {results['skip']} skip")
    print(f"{'='*60}")

    if results["errors"]:
        print(f"\nFailed parameters:")
        for err in results["errors"]:
            print(f"  {err['block']}/{err['param']}: sent={err.get('sent')}, got={err.get('got')}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Round-trip parameter test (requires FM9)")
    parser.add_argument("--block", help="Filter by block name (partial match)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tested without sending")
    args = parser.parse_args()

    midi = FractalMidi()
    midi.configure("fm9")
    midi.connect()
    print(f"Connected to FM9")

    results = run_test(midi, block_filter=args.block, dry_run=args.dry_run)

    # Save results
    output_path = Path(__file__).parent / "roundtrip_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
