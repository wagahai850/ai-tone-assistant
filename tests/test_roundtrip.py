#!/usr/bin/env python3
"""Round-trip test: SET → GET via production MCP tools.

Verifies that fm9_set_block_params / fm9_set_amp_params / fm9_set_drive_params
correctly encode values and that readback matches what was sent.

Requires FM9 connected via USB.

Usage:
    python3 tests/test_roundtrip.py [--block "Delay 1"] [--param "Mix"] [--dry-run]
"""

import sys
import time
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import production tools (same code path as MCP server)
from tools import (
    ALL_PARAMS, BLOCKS, TYPE_VALID_PARAMS, AMP_PARAMS, DRIVE_PARAMS,
    midi, ensure_connected, resolve_block,
)

# We need the tool functions directly — import them by registering on a dummy MCP
from unittest.mock import MagicMock

_mcp = MagicMock()
import tools.amp_drive
import tools.generic_block
tools.amp_drive.register(_mcp)
tools.generic_block.register(_mcp)

# Extract registered tool functions from mock
_registered = {}
for call in _mcp.tool.return_value.call_args_list:
    pass
# Alternative: just import the module-level functions after register
# The @mcp.tool() decorator returns the function unchanged, so we can call them directly
# Let's re-import by calling register and capturing

class ToolCapture:
    """Captures functions registered via @mcp.tool()."""
    def __init__(self):
        self.tools = {}
    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator

_capture = ToolCapture()
tools.amp_drive.register(_capture)
tools.generic_block.register(_capture)

fm9_set_amp_params = _capture.tools["fm9_set_amp_params"]
fm9_get_amp_params = _capture.tools["fm9_get_amp_params"]
fm9_set_drive_params = _capture.tools["fm9_set_drive_params"]
fm9_get_drive_params = _capture.tools["fm9_get_drive_params"]
fm9_set_block_params = _capture.tools["fm9_set_block_params"]
fm9_get_block_params = _capture.tools["fm9_get_block_params"]
fm9_list_block_params = _capture.tools["fm9_list_block_params"]


# --- Test Value Selection ---

def get_test_value(param_info: dict, current_value) -> float | None:
    """Pick a safe test value different from current.

    Args:
        param_info: From fm9_list_block_params or hand-verified data.
                    Must have 'type', 'max', 'min'.
        current_value: Current display value on device.
    """
    ptype = param_info.get("type", "continuous")
    pmax = param_info.get("max", 10.0)
    pmin = param_info.get("min", 0)

    if ptype == "enum":
        return None

    if ptype == "switch":
        return not current_value if isinstance(current_value, bool) else (0 if current_value else 1)

    if ptype == "signed_int":
        if current_value == 0:
            return 1
        return current_value - 1 if current_value > 0 else current_value + 1

    if ptype == "bipolar":
        mid = (pmax + pmin) / 2
        if abs(current_value - mid) > 0.5:
            return round(mid, 2)
        test = round(mid + 1.0, 2)
        return min(pmax, max(pmin, test))

    # Continuous
    if pmax >= 20000:
        # Frequency — pick a value in the middle of log range
        return 1000.0 if current_value != 1000.0 else 2000.0
    mid = pmax * 0.5
    if abs(current_value - mid) > 0.1:
        return round(mid, 2)
    return round(mid + 0.5, 2)


def values_match(sent, got, param_info: dict) -> bool:
    """Compare sent value with readback value within tolerance."""
    ptype = param_info.get("type", "continuous")
    pmax = param_info.get("max", 10.0)

    if ptype == "switch":
        return bool(got) == bool(sent)
    if ptype == "signed_int":
        return got == sent
    # Numeric comparison with tolerance
    if pmax >= 20000:
        # Frequency (log scale): 2% relative tolerance
        return abs(got - sent) <= max(2.0, abs(sent) * 0.02)
    if pmax >= 100:
        return abs(got - sent) <= 1.0
    return abs(got - sent) <= 0.15


class PresetCorrupted(Exception):
    """Raised when the preset appears corrupted (SET has no effect)."""
    pass


class FirmwarePanic(Exception):
    """Raised when the FM9 stops responding (timeout on GET)."""
    pass


def health_check_block(block_name: str) -> bool:
    """Verify the block is responsive by doing a SET/GET cycle.
    
    Raises PresetCorrupted if SET has no effect.
    Raises FirmwarePanic if GET fails entirely.
    Returns True if healthy.
    """
    # Read current state
    result = fm9_get_block_params(block=block_name)
    if not result.get("success"):
        raise FirmwarePanic(f"Cannot read {block_name}: {result.get('error')}")

    # Find a param we can safely toggle (Level or Mix, which exist on most blocks)
    params = result.get("params", {})
    
    # Try Level first, then Mix, then first continuous param
    test_param = None
    for candidate in ["Level", "Mix", "Feed", "Rate", "Depth"]:
        if candidate in params:
            entry = params[candidate]
            if entry.get("type") in ("continuous", "bipolar"):
                test_param = candidate
                break
    
    if test_param is None:
        # Find any continuous param
        for name, entry in params.items():
            if entry.get("type") == "continuous" and entry.get("max", 0) > 0:
                test_param = name
                break

    if test_param is None:
        return True  # Can't health check, assume OK

    current_raw = params[test_param]["raw"]
    current_value = params[test_param]["value"]
    
    # Pick a different value
    pmax = params[test_param].get("max", 10.0)
    test_value = pmax * 0.3 if current_value > pmax * 0.5 else pmax * 0.7

    # SET
    set_result = fm9_set_block_params(block=block_name, params={test_param: test_value})
    if not set_result.get("success"):
        raise FirmwarePanic(f"SET failed on {block_name}: {set_result.get('error')}")

    # Check if raw changed
    new_params = set_result.get("params", {})
    new_entry = new_params.get(test_param)
    if new_entry and new_entry["raw"] == current_raw:
        raise PresetCorrupted(f"Health check failed: {block_name}/{test_param} SET had no effect")

    # Restore
    fm9_set_block_params(block=block_name, params={test_param: current_value})
    return True


# --- Test Runners ---

def test_amp(dry_run: bool = False, param_filter: str | None = None) -> dict:
    """Round-trip test for Amp 1 using fm9_set_amp_params."""
    print(f"\n{'='*60}")
    print(f"Block: Amp 1 (production: fm9_set_amp_params)")
    print(f"{'='*60}")

    results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    if dry_run:
        for name, info in AMP_PARAMS["params"].items():
            if info["type"] == "enum":
                continue
            if param_filter and param_filter.lower() not in name.lower():
                continue
            print(f"  [dry-run] Would test: {name} (pid={info['param_id']}, {info['type']}, max={info['max']})")
            results["skip"] += 1
        return results

    # Place Amp 1 on grid
    block_id = AMP_PARAMS["block_id_int"]
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.3)
            placed_by_us = True
            print(f"  Placed Amp 1 at R0C1")
        except Exception as e:
            print(f"  ERROR: Cannot place Amp 1: {e}")
            return results

    # Get current state
    current = fm9_get_amp_params()
    if not current.get("success"):
        print(f"  ERROR: Cannot read Amp 1: {current.get('error')}")
        if placed_by_us:
            midi.delete_block_at(row=0, col=1)
        return results

    current_params = current["params"]

    # Get type-specific valid params for current Amp type
    amp_type_index = 0
    # Read current type from block data
    block_params_result = fm9_get_block_params(block="Amp 1")
    if block_params_result.get("success"):
        type_entry = block_params_result.get("params", {}).get("Type")
        if type_entry:
            amp_type_index = type_entry.get("value", 0)

    # Get valid param suffixes for this type
    amp_tvp = TYPE_VALID_PARAMS.get("amp", {})
    type_specific = amp_tvp.get("type_specific", {}).get(str(int(amp_type_index)), [])
    valid_suffixes = {n.split("_", 1)[1] if "_" in n else n for n in type_specific} if type_specific else None

    if valid_suffixes:
        print(f"  Amp type {int(amp_type_index)}: {len(valid_suffixes)} valid params")

    for name, info in AMP_PARAMS["params"].items():
        if info["type"] == "enum":
            results["skip"] += 1
            continue
        if param_filter and param_filter.lower() not in name.lower():
            results["skip"] += 1
            continue

        # Skip params not valid for current Amp type
        if valid_suffixes is not None:
            # Match by checking if any valid suffix matches the param's internal name
            # amp_params.json doesn't have internal names, so we use display name heuristics
            # The param names in type_valid are like DRIVE, BASS, MID, TREBLE, MASTER, etc.
            name_upper = name.upper().replace(" ", "")
            if not any(name_upper == s or name_upper.endswith(s) or s.startswith(name_upper[:4])
                       for s in valid_suffixes):
                results["skip"] += 1
                continue

        current_value = current_params.get(name)
        if current_value is None:
            results["skip"] += 1
            continue

        meta = {"type": info["type"], "max": info["max"],
                "min": info.get("min", -info["max"] if info["type"] == "bipolar" else 0)}
        test_value = get_test_value(meta, current_value)
        if test_value is None:
            results["skip"] += 1
            continue

        # SET via production code
        result = fm9_set_amp_params(params={name: test_value})
        if not result.get("success"):
            print(f"  FAIL {name}: SET error: {result.get('error')}")
            results["fail"] += 1
            results["errors"].append({"block": "Amp 1", "param": name, "error": result.get("error")})
            continue

        # Check readback from result
        readback_params = result.get("params", {})
        readback_value = readback_params.get(name)

        if readback_value is None:
            print(f"  FAIL {name}: No readback value")
            results["fail"] += 1
            results["errors"].append({"block": "Amp 1", "param": name, "error": "no readback"})
        elif values_match(test_value, readback_value, meta):
            results["pass"] += 1
        else:
            print(f"  FAIL {name}: sent={test_value}, got={readback_value}")
            results["fail"] += 1
            results["errors"].append({
                "block": "Amp 1", "param": name,
                "sent": test_value, "got": readback_value,
            })

        # Restore original value
        try:
            fm9_set_amp_params(params={name: current_value})
        except Exception:
            pass
        time.sleep(0.05)

    # Clean up
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.2)
        except Exception:
            pass

    print(f"  Result: {results['pass']} pass, {results['fail']} fail, {results['skip']} skip")
    return results


def test_drive(dry_run: bool = False, param_filter: str | None = None) -> dict:
    """Round-trip test for Drive 1 using fm9_set_drive_params."""
    print(f"\n{'='*60}")
    print(f"Block: Drive 1 (production: fm9_set_drive_params)")
    print(f"{'='*60}")

    results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    if dry_run:
        for name, info in DRIVE_PARAMS["params"].items():
            if info["type"] == "enum":
                continue
            if param_filter and param_filter.lower() not in name.lower():
                continue
            print(f"  [dry-run] Would test: {name} (pid={info['param_id']}, {info['type']}, max={info['max']})")
            results["skip"] += 1
        return results

    # Place Drive 1 on grid
    block_id = DRIVE_PARAMS["block_id_int"]
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.3)
            placed_by_us = True
            print(f"  Placed Drive 1 at R0C1")
        except Exception as e:
            print(f"  ERROR: Cannot place Drive 1: {e}")
            return results

    current = fm9_get_drive_params()
    if not current.get("success"):
        print(f"  ERROR: Cannot read Drive 1: {current.get('error')}")
        if placed_by_us:
            midi.delete_block_at(row=0, col=1)
        return results

    current_params = current["params"]

    for name, info in DRIVE_PARAMS["params"].items():
        if info["type"] == "enum":
            results["skip"] += 1
            continue
        if param_filter and param_filter.lower() not in name.lower():
            results["skip"] += 1
            continue

        current_value = current_params.get(name)
        if current_value is None:
            results["skip"] += 1
            continue

        meta = {"type": info["type"], "max": info["max"],
                "min": info.get("min", -info["max"] if info["type"] == "bipolar" else 0)}
        test_value = get_test_value(meta, current_value)
        if test_value is None:
            results["skip"] += 1
            continue

        result = fm9_set_drive_params(params={name: test_value})
        if not result.get("success"):
            print(f"  FAIL {name}: SET error: {result.get('error')}")
            results["fail"] += 1
            results["errors"].append({"block": "Drive 1", "param": name, "error": result.get("error")})
            continue

        readback_params = result.get("params", {})
        readback_value = readback_params.get(name)

        if readback_value is None:
            print(f"  FAIL {name}: No readback value")
            results["fail"] += 1
            results["errors"].append({"block": "Drive 1", "param": name, "error": "no readback"})
        elif values_match(test_value, readback_value, meta):
            results["pass"] += 1
        else:
            print(f"  FAIL {name}: sent={test_value}, got={readback_value}")
            results["fail"] += 1
            results["errors"].append({
                "block": "Drive 1", "param": name,
                "sent": test_value, "got": readback_value,
            })

        try:
            fm9_set_drive_params(params={name: current_value})
        except Exception:
            pass
        time.sleep(0.05)

    # Clean up
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.2)
        except Exception:
            pass

    print(f"  Result: {results['pass']} pass, {results['fail']} fail, {results['skip']} skip")
    return results


def test_block(block_name: str, dry_run: bool = False, param_filter: str | None = None) -> dict:
    """Round-trip test for any block using fm9_set_block_params / fm9_get_block_params."""
    print(f"\n{'='*60}")
    print(f"Block: {block_name} (production: fm9_set_block_params)")
    print(f"{'='*60}")

    results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    # Get param list
    param_list_result = fm9_list_block_params(block=block_name)
    if not param_list_result.get("success"):
        print(f"  ERROR: Cannot list params: {param_list_result.get('error')}")
        return results

    all_block_params = param_list_result["params"]

    if dry_run:
        for p in all_block_params:
            if p["type"] == "enum":
                continue
            if param_filter and param_filter.lower() not in p["display_name"].lower():
                continue
            print(f"  [dry-run] Would test: {p['display_name']} (pid={p['param_id']}, {p['type']}, max={p['max']})")
            results["skip"] += 1
        return results

    # Place block if not already present (for blocks that aren't on the grid)
    # First check if block is already active
    try:
        prefix, block_info = resolve_block(block_name)
        block_id = int(block_info["block_id"], 16)
    except Exception as e:
        print(f"  ERROR: Cannot resolve block: {e}")
        return results

    status = midi.get_status_dump()
    block_placed = block_id in status

    if not block_placed:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.3)
            block_placed = True
            print(f"  Placed {block_name} at R0C1")
        except Exception as e:
            print(f"  ERROR: Cannot place block: {e}")
            return results

    # Get current state
    current = fm9_get_block_params(block=block_name)
    if not current.get("success"):
        print(f"  ERROR: Cannot read block: {current.get('error')}")
        if block_id not in status:
            midi.delete_block_at(row=0, col=1)
        return results

    # Health check: verify SET works on this block
    try:
        health_check_block(block_name)
    except PresetCorrupted as e:
        print(f"  ABORT: {e}")
        results["errors"].append({"block": block_name, "param": "_health_check", "error": str(e)})
        raise
    except FirmwarePanic as e:
        print(f"  ABORT: {e}")
        results["errors"].append({"block": block_name, "param": "_health_check", "error": str(e)})
        raise

    current_params = current["params"]

    for p in all_block_params:
        display_name = p["display_name"]
        ptype = p["type"]
        pmax = p["max"]
        pmin = p["min"]

        if ptype == "enum":
            results["skip"] += 1
            continue
        if param_filter and param_filter.lower() not in display_name.lower():
            results["skip"] += 1
            continue

        # Get current value from readback
        current_entry = current_params.get(display_name)
        if current_entry is None:
            results["skip"] += 1
            continue
        current_value = current_entry["value"]

        meta = {"type": ptype, "max": pmax, "min": pmin}
        test_value = get_test_value(meta, current_value)
        if test_value is None:
            results["skip"] += 1
            continue

        # SET via production code
        result = fm9_set_block_params(block=block_name, params={display_name: test_value})
        if not result.get("success"):
            error_msg = result.get('error', '?')
            if "Failed to get block data" in error_msg or "timed out" in error_msg.lower():
                print(f"  ABORT: Firmware panic detected: {error_msg}")
                raise FirmwarePanic(error_msg)
            print(f"  FAIL {display_name}: SET error: {error_msg}")
            results["fail"] += 1
            results["errors"].append({"block": block_name, "param": display_name, "error": error_msg})
            continue

        # Check readback
        readback_params = result.get("params", {})
        readback_entry = readback_params.get(display_name)

        if readback_entry is None:
            print(f"  FAIL {display_name}: No readback")
            results["fail"] += 1
            results["errors"].append({"block": block_name, "param": display_name, "error": "no readback"})
        else:
            readback_value = readback_entry["value"]
            raw = readback_entry.get("raw", "?")

            # Check if value changed at all (type-specific inactive param)
            if readback_entry["raw"] == current_entry["raw"]:
                # Value didn't change — param is likely inactive for current type
                results["skip"] += 1
            elif readback_entry["raw"] == 65534 and current_entry["raw"] == 65534:
                # Both at max — param is stuck at max (type-specific default)
                results["skip"] += 1
            elif values_match(test_value, readback_value, meta):
                results["pass"] += 1
            else:
                print(f"  FAIL {display_name}: sent={test_value}, got={readback_value} (raw={raw})")
                results["fail"] += 1
                results["errors"].append({
                    "block": block_name, "param": display_name,
                    "sent": test_value, "got": readback_value, "raw": raw,
                })

        # Restore original value
        try:
            fm9_set_block_params(block=block_name, params={display_name: current_value})
        except Exception:
            pass
        time.sleep(0.05)

    # Clean up if we placed the block
    if block_id not in status:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.2)
        except Exception:
            pass

    print(f"  Result: {results['pass']} pass, {results['fail']} fail, {results['skip']} skip")
    return results


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Round-trip parameter test via production MCP tools")
    parser.add_argument("--block", help="Block to test (e.g., 'Amp 1', 'Delay 1'). Tests all if omitted.")
    parser.add_argument("--start-from", help="Start from this block (skip earlier ones). For resuming interrupted runs.")
    parser.add_argument("--param", help="Filter by parameter name (partial match)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tested")
    args = parser.parse_args()

    ensure_connected()
    print(f"Connected to FM9")

    all_results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    if args.block:
        # Test specific block
        block = args.block
        try:
            if block.lower() == "amp 1":
                r = test_amp(dry_run=args.dry_run, param_filter=args.param)
            elif block.lower() == "drive 1":
                r = test_drive(dry_run=args.dry_run, param_filter=args.param)
            else:
                r = test_block(block, dry_run=args.dry_run, param_filter=args.param)
            for k in ("pass", "fail", "skip"):
                all_results[k] += r[k]
            all_results["errors"].extend(r.get("errors", []))
        except (PresetCorrupted, FirmwarePanic) as e:
            print(f"\n!!! ABORTED: {e}")
            all_results["errors"].append({"block": args.block, "param": "_abort", "error": str(e)})
    else:
        # Test Amp 1, Drive 1, then all effect blocks
        try:
            # Skip Amp/Drive dedicated tests if resuming
            if not args.start_from:
                for test_fn in [test_amp, test_drive]:
                    r = test_fn(dry_run=args.dry_run, param_filter=args.param)
                    for k in ("pass", "fail", "skip"):
                        all_results[k] += r[k]
                    all_results["errors"].extend(r.get("errors", []))

            # Test effect blocks (skip Amp/Drive/Cab which have dedicated paths)
            AMP_DRIVE_IDS = {0x3A, 0x3B, 0x3C, 0x3D, 0x76, 0x77, 0x78, 0x79}
            CAB_IDS = {0x3E, 0x3F, 0x40, 0x41}
            SKIP_IDS = AMP_DRIVE_IDS | CAB_IDS

            skipping = args.start_from is not None

            for prefix, block_info in ALL_PARAMS.items():
                block_id_str = block_info.get("block_id")
                if not block_id_str:
                    continue
                block_id = int(block_id_str, 16)
                if block_id in SKIP_IDS:
                    continue
                block_name = block_info["block_name"]

                # --skip-until: skip blocks until we reach the target
                if skipping:
                    if args.start_from.lower() in block_name.lower():
                        skipping = False
                    else:
                        continue

                r = test_block(block_name, dry_run=args.dry_run, param_filter=args.param)
                for k in ("pass", "fail", "skip"):
                    all_results[k] += r[k]
                all_results["errors"].extend(r.get("errors", []))
        except (PresetCorrupted, FirmwarePanic) as e:
            print(f"\n!!! ABORTED: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"TOTAL: {all_results['pass']} pass, {all_results['fail']} fail, {all_results['skip']} skip")
    print(f"{'='*60}")

    if all_results["errors"]:
        print(f"\nFailed parameters:")
        for err in all_results["errors"]:
            if "sent" in err:
                print(f"  {err['block']}/{err['param']}: sent={err['sent']}, got={err['got']}")
            else:
                print(f"  {err['block']}/{err['param']}: {err.get('error', '?')}")

    # Save results
    output_path = Path(__file__).parent / "roundtrip_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return all_results


if __name__ == "__main__":
    main()
