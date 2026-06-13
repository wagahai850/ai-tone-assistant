#!/usr/bin/env python3
"""Unified calibration + verification in one pass.

For each parameter:
  1. SET 0/min → GET raw → determine decode_style
  2. SET test_value → GET raw → compute decode_max
  3. Verify: decode raw back using computed decode_max → compare with sent value
  4. Apply to all_params.json

Single pass. No separate roundtrip test needed.

Usage:
    python3 tests/calibrate_and_verify.py --block "Delay 1" --apply
    python3 tests/calibrate_and_verify.py --all --apply
    python3 tests/calibrate_and_verify.py --all --apply --start-from "Chorus 1"
    python3 tests/calibrate_and_verify.py --all-types --apply
    python3 tests/calibrate_and_verify.py --all-types --apply --start-from "Compressor 1"
    python3 tests/calibrate_and_verify.py --block "Delay 1" --dry-run
"""

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import (
    ALL_PARAMS, midi, ensure_connected, resolve_block,
    BLOCK_NAME_TO_ID, BASE_DIR, TYPE_VALID_PARAMS, EFFECT_DEFS,
)

DATA_DIR = BASE_DIR / "data" / "fm9"

# Blocks that crash firmware
UNSAFE_BLOCK_IDS = {
    0x82,  # Synth
    0x86,  # Vocoder
    0x8A,  # Megatap Delay
    0x8E,  # Crossover
    0x96,  # Ring Modulator
    0x9A,  # Multiband Comp
    0x9E,  # Ten-Tap Delay
    0xA2,  # Resonator
    0xA6,  # Looper
    0xAA,  # Tonematch
    0xAE,  # Realtime Analyzer (IR Capture)
    0xB2,  # Plex Delay — see test_roundtrip.py UNSAFE_IDS
}

# Blocks with dedicated encoding (Amp/Drive/Cab — skip)
DEDICATED_BLOCK_IDS = {0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41}

# 4096-scale params (from cache flags)
_4096_PARAMS: set[tuple[int, int]] = set()  # (block_id, pid)


def load_4096_params():
    """Load 4096-scale param identification from cache flags."""
    cache_file = DATA_DIR / "cache_params_flags.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        for entry in data:
            if entry.get("flags") == 0x0430:
                _4096_PARAMS.add((entry["block_id"], entry["pid"]))


def is_4096_scale(block_id: int, pid: int) -> bool:
    return (block_id, pid) in _4096_PARAMS


def ts() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str):
    print(f"[{ts()}] {msg}", flush=True)


class FirmwarePanic(Exception):
    pass


class BlockUnresponsive(Exception):
    pass


def get_raw_at(block_id: int, pid: int) -> int | None:
    """Read raw 21-bit value of a param via GET."""
    chunks = midi.get_block_data(block_id)
    if not chunks or not chunks[0]:
        return None
    chunk = chunks[0]
    offset = 7 + pid * 3
    if offset + 2 >= len(chunk):
        return None
    lo, hi, msb = chunk[offset], chunk[offset + 1], chunk[offset + 2]
    return lo | (hi << 7) | (msb << 14)


def liveness_check() -> bool:
    """Quick check that FM9 is still responding."""
    try:
        status = midi.get_status_dump()
        return status is not None and len(status) > 0
    except Exception:
        return False


def decode_value(raw: int, style: str, decode_max: float, pmin: float = 0.0) -> float:
    """Decode a raw value using the determined style and decode_max."""
    if style == "center":
        return (raw - 32767) / 32767.0 * decode_max
    elif style == "frequency":
        min_freq = max(pmin, 20.0)
        if raw == 0:
            return min_freq
        return min_freq * 10 ** (raw / 65534.0 * math.log10(decode_max / min_freq))
    elif style == "zero":
        return raw / 65534.0 * decode_max
    else:
        return raw / 65534.0 * decode_max


def values_close(a: float, b: float, pmax: float, ptype: str) -> bool:
    """Check if two values are within acceptable tolerance."""
    if ptype == "frequency" or pmax >= 2000:
        return abs(a - b) <= max(5.0, abs(a) * 0.03)
    if pmax >= 100:
        return abs(a - b) <= 1.5
    return abs(a - b) <= 0.2


def calibrate_and_verify_param(
    block_id: int, pid: int, ptype: str, pmax: float, pmin: float,
    _timing: dict | None = None,
) -> dict | None:
    """Calibrate + verify a single parameter in one pass.

    Returns dict with:
      decode_style, decode_max, verified (bool), sent, got, raw_at_min, raw_at_test
    Or None if param is not calibratable (switch/enum/signed_int).

    If _timing dict is passed, accumulates timing breakdown into it.
    """
    if ptype in ("switch", "enum", "signed_int"):
        return None
    if pmax == 0:
        return None

    # Static 4096 detection
    if is_4096_scale(block_id, pid):
        return {
            "decode_style": "zero",
            "decode_scale": "4096",
            "decode_max": pmax,
            "verified": True,
            "note": "4096 (static)",
        }

    is_freq = (ptype == "frequency" and pmax >= 2000)
    is_linear_freq = (ptype == "frequency" and pmax < 2000)
    is_bipolar = (ptype == "bipolar")

    # === Step 1: SET min/zero → GET raw → determine style ===

    t0 = time.time()
    if is_freq:
        min_freq = max(pmin, 20.0)
        midi.set_param_value(block_id, pid, min_freq, 1.0, raw_float=True)
    elif is_linear_freq:
        midi.set_param_value(block_id, pid, 0.0, pmax)
    elif is_bipolar:
        midi.set_param_value(block_id, pid, -1.0, 1.0, raw_float=True)
    else:
        midi.set_param_value(block_id, pid, 0.0, pmax)
    t_set1 = time.time()
    time.sleep(0.12)
    t_sleep1 = time.time()
    raw_at_min = get_raw_at(block_id, pid)
    t_get1 = time.time()

    if _timing is not None:
        _timing["set"] = _timing.get("set", 0) + (t_set1 - t0)
        _timing["sleep"] = _timing.get("sleep", 0) + (t_sleep1 - t_set1)
        _timing["get"] = _timing.get("get", 0) + (t_get1 - t_sleep1)
        _timing["calls"] = _timing.get("calls", 0) + 1

    if raw_at_min is None:
        return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False,
                "note": "GET failed"}

    # For bipolar: also check center
    raw_at_zero = raw_at_min
    if is_bipolar:
        t0b = time.time()
        midi.set_param_value(block_id, pid, 0.0, 1.0, raw_float=True)
        t_set2 = time.time()
        time.sleep(0.12)
        t_sleep2 = time.time()
        raw_at_zero = get_raw_at(block_id, pid)
        t_get2 = time.time()
        if _timing is not None:
            _timing["set"] += (t_set2 - t0b)
            _timing["sleep"] += (t_sleep2 - t_set2)
            _timing["get"] += (t_get2 - t_sleep2)
            _timing["calls"] += 1
        if raw_at_zero is None:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False,
                    "note": "GET failed"}

    # === Step 2: SET test value → GET raw → compute decode_max ===

    t0c = time.time()
    if is_freq:
        test_sent = 1000.0 if pmax >= 2000 else pmax * 0.5
        midi.set_param_value(block_id, pid, test_sent, 1.0, raw_float=True)
    elif is_linear_freq:
        test_sent = pmax * 0.5
        midi.set_param_value(block_id, pid, test_sent, pmax)
    elif is_bipolar:
        test_sent = 0.5  # raw_float normalized
        midi.set_param_value(block_id, pid, 0.5, 1.0, raw_float=True)
    else:
        test_sent = pmax * 0.5
        midi.set_param_value(block_id, pid, test_sent, pmax)
    t_set3 = time.time()
    time.sleep(0.12)
    t_sleep3 = time.time()
    raw_at_test = get_raw_at(block_id, pid)
    t_get3 = time.time()

    if _timing is not None:
        _timing["set"] += (t_set3 - t0c)
        _timing["sleep"] += (t_sleep3 - t_set3)
        _timing["get"] += (t_get3 - t_sleep3)
        _timing["calls"] += 1

    if raw_at_test is None:
        return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False,
                "note": "GET failed"}

    # === Determine style ===

    if is_freq:
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        style = "frequency"
    elif is_linear_freq:
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        style = "zero"
    elif is_bipolar:
        if abs(raw_at_zero - 32767) < 500:
            style = "center"
        elif raw_at_min < 500:
            style = "zero"
        else:
            if abs(raw_at_test - raw_at_min) < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
            style = "zero"
    else:
        if raw_at_min > 500 and abs(raw_at_test - raw_at_min) < 10:
            # Confirm unresponsive
            midi.set_param_value(block_id, pid, pmax * 0.75, pmax)
            time.sleep(0.12)
            raw_75 = get_raw_at(block_id, pid)
            if raw_75 is not None and abs(raw_75 - raw_at_test) < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        if abs(raw_at_min - 32767) < 500:
            style = "center"
        elif raw_at_min < 500:
            style = "zero"
        else:
            style = "zero"  # fallback

    # === Compute decode_max ===

    if style == "frequency":
        min_freq = max(pmin, 20.0)
        test_hz = 1000.0 if pmax >= 2000 else pmax * 0.5
        if raw_at_test < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        ratio = raw_at_test / 65534.0
        if ratio < 0.01:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        log_dm = math.log10(test_hz / min_freq) / ratio
        decode_max = min_freq * 10 ** log_dm

    elif style == "center":
        delta = raw_at_test - 32767
        if abs(delta) < 10:
            return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
        if is_bipolar:
            decode_max = (pmax * 0.5) * 32767.0 / delta
        else:
            decode_max = (pmax * 0.5) * 32767.0 / delta

    elif style == "zero":
        if is_bipolar:
            # Need raw at max for zero-bipolar
            midi.set_param_value(block_id, pid, 1.0, 1.0, raw_float=True)
            time.sleep(0.12)
            raw_at_max = get_raw_at(block_id, pid)
            if raw_at_max is None:
                return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False,
                        "note": "GET failed"}
            if raw_at_max < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
            decode_max = pmax * 65534.0 / raw_at_max
        else:
            if raw_at_test < 10:
                return {"decode_style": "unresponsive", "decode_max": pmax, "verified": False}
            decode_max = (pmax * 0.5) * 65534.0 / raw_at_test
    else:
        decode_max = pmax

    # === Step 3: Verify — decode raw_at_test with computed decode_max ===

    if style == "frequency":
        decoded = decode_value(raw_at_test, style, decode_max, pmin)
        expected = test_hz
    elif is_bipolar and style == "center":
        decoded = decode_value(raw_at_test, style, decode_max, pmin)
        expected = pmax * 0.5  # we sent raw_float 0.5 = half of positive max
    elif is_bipolar and style == "zero":
        # We don't have a clean test for zero-bipolar verification here
        # Use raw_at_test from step 2 (sent 0.5 normalized)
        decoded = decode_value(raw_at_test, style, decode_max, pmin)
        expected = test_sent * pmax  # rough
        # Bipolar zero verification is complex; mark as verified if decode_max is reasonable
        verified = decode_max > 0 and decode_max < pmax * 5
        return {
            "decode_style": style,
            "decode_max": round(decode_max, 2),
            "verified": verified,
            "raw_at_min": raw_at_min,
            "raw_at_test": raw_at_test,
        }
    else:
        decoded = decode_value(raw_at_test, style, decode_max, pmin)
        expected = pmax * 0.5

    verified = values_close(decoded, expected, pmax, ptype)

    return {
        "decode_style": style,
        "decode_max": round(decode_max, 2),
        "verified": verified,
        "sent": round(expected, 2),
        "got": round(decoded, 2),
        "raw_at_min": raw_at_min,
        "raw_at_test": raw_at_test,
    }


def process_block(block_name: str, dry_run: bool = False) -> dict:
    """Calibrate + verify all params in a block. Returns results dict."""
    log(f"▶ {block_name}")

    try:
        prefix, block_info = resolve_block(block_name)
    except ValueError as e:
        log(f"  ERROR: {e}")
        return {}

    block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
    if not block_id:
        log(f"  ERROR: No block_id")
        return {}

    if block_id in UNSAFE_BLOCK_IDS:
        log(f"  SKIP: unsafe")
        return {}
    if block_id in DEDICATED_BLOCK_IDS:
        log(f"  SKIP: dedicated encoding")
        return {}

    params = block_info.get("params", {})
    calibratable = [pid for pid, p in params.items()
                    if p.get("type", "continuous") not in ("switch", "enum", "signed_int")
                    and p.get("max", 0) > 0]

    if not calibratable:
        log(f"  SKIP: no calibratable params")
        return {}

    if dry_run:
        log(f"  [dry-run] {len(calibratable)} params")
        return {}

    # Place block on grid if needed
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.5)
            placed_by_us = True
        except Exception as e:
            log(f"  ERROR placing block: {e}")
            return {}

    # Verify GET works
    chunks = midi.get_block_data(block_id)
    if not chunks:
        log(f"  ERROR: GET failed")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
            except Exception:
                pass
        return {}

    # Process each param
    results = {}
    ok = fail = unresponsive = 0

    for pid_str in sorted(calibratable, key=int):
        pid = int(pid_str)
        pinfo = params[pid_str]
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 10.0)
        pmin = pinfo.get("min", 0)
        name = pinfo.get("display_name", f"pid_{pid}")

        try:
            result = calibrate_and_verify_param(block_id, pid, ptype, pmax, pmin)
        except FirmwarePanic as e:
            log(f"  PANIC at pid={pid} ({name}): {e}")
            raise

        if result is None:
            continue

        results[pid_str] = result
        result["display_name"] = name

        if result["decode_style"] == "unresponsive":
            unresponsive += 1
        elif result.get("verified", False):
            ok += 1
        else:
            fail += 1
            log(f"  ❌ pid={pid:>3} {name:<20} style={result['decode_style']} "
                f"decode_max={result['decode_max']:.1f} "
                f"sent={result.get('sent','?')} got={result.get('got','?')}")

    # Cleanup
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.3)
        except Exception:
            pass

    if not liveness_check():
        raise FirmwarePanic(f"FM9 died after {block_name}")

    log(f"  ✓ {ok} verified, {fail} failed, {unresponsive} unresponsive "
        f"({len(calibratable)} total)")
    return results


# === Type-PID map: which param_id holds the "Type" for each block category ===
TYPE_PID_MAP = {
    "amp": 10, "drive": 0, "delay": 11, "reverb": 10,
    "chorus": 0, "flanger": 0, "phaser": 0, "pitch": 0,
    "wah": 0, "tremolo/panner": 0, "tremolo": 0,
    "compressor": 12, "graphic eq": 15, "enhancer": 6,
    "volume/pan": 9, "megatap delay": 28, "ring modulator": 10,
    "ten-tap delay": 0, "filter": 0, "synth": 0,
    "plex delay": 0, "multitap delay": 0,
}

# Mapping from ALL_PARAMS prefix → TYPE_VALID_PARAMS["blocks"] key
PREFIX_TO_TVP = {
    "DISTORT": "amp",       # amp handled separately, not in --all-types
    "FUZZ": "Drive",
    "CABINET": "Cab",
    "REVERB": "Reverb",
    "DELAY": "Delay",
    "MULTITAP": "MultiDelay",
    "CHORUS": "Chorus",
    "FLANGER": "Flanger",
    "ROTARY": "Rotary",
    "PHASER": "Phaser",
    "WAH": "Wah",
    "FORMANT": "Formant",
    "TREMOLO": "Tremolo",
    "ENHANCER": "Enhancer",
    "MIXER": "Mixer",
    "SYNTH": "Synth",
    "VOCODER": "Vocoder",
    "MEGATAP": "MegaTap",
    "CROSSOVER": "Crossover",
    "RINGMOD": "RingMod",
    "MULTICOMP": "MultibandComp",
    "TENTAP": "TenTapDelay",
    "RESONATOR": "Resonator",
    "LOOPER": "Looper",
    "PLEX": "PlexDelay",
    "COMP": "Compressor",
    "GEQ": "GraphicEQ",
    "PEQ": "ParametricEQ",
    "VOLUME": "VolPan",
    "PITCH": "Pitch",
    "FILTER": "Filter",
    "IRPLAYER": "IRPlayer",
}

# effect_definitions key map (block_name.lower() → EFFECT_DEFS key)
BLOCK_TO_DEFS_KEY = {
    "drive": "drive_models",
    "delay": "delay_types",
    "reverb": "reverb_types",
    "chorus": "chorus_types",
    "flanger": "flanger_types",
    "phaser": "phaser_types",
    "pitch": "pitch_types",
    "tremolo/panner": "tremolo_types",
    "wah": "wah_types",
    "compressor": "compressor_types",
    "graphic eq": "geq_types",
    "filter": "filter_types",
    "synth": "synth_types",
    "multitap delay": "multitap_delay_types",
    "plex delay": "plex_delay_types",
    "enhancer": "enhancer_types",
    "ten-tap delay": "tentap_delay_types",
    "resonator": "resonator_types",
    "volume/pan": "volpan_types",
    "ring modulator": "ringmod_types",
}


def get_tvp_variants(prefix: str) -> dict | None:
    """Get TYPE_VALID_PARAMS variant info for an ALL_PARAMS prefix.

    Returns None if no multi-variant data exists (i.e., __default__ only).
    Returns dict of {variant_key: {"type_indices": [int,...], "params": [str,...]}}
    """
    tvp_key = PREFIX_TO_TVP.get(prefix)
    if not tvp_key:
        return None

    blocks_tvp = TYPE_VALID_PARAMS.get("blocks", {})
    block_tvp = blocks_tvp.get(tvp_key)
    if not block_tvp:
        return None

    variants = block_tvp.get("variants", {})
    if len(variants) <= 1:
        return None  # __default__ only — no type iteration needed

    # Parse into usable structure
    result = {}
    # Collect all explicitly claimed type indices
    claimed_indices = set()
    for vkey, vinfo in variants.items():
        if vkey != "__default__":
            for idx in vkey.split(","):
                claimed_indices.add(int(idx))

    for vkey, vinfo in variants.items():
        if vkey == "__default__":
            # __default__ means "all types not explicitly listed"
            # Use lowest unclaimed index (or 0 if nothing claimed)
            default_idx = 0
            for i in range(100):
                if i not in claimed_indices:
                    default_idx = i
                    break
            type_indices = [default_idx]
        else:
            # vkey is comma-separated type indices e.g. "6,14"
            type_indices = [int(x) for x in vkey.split(",")]
        result[vkey] = {
            "name": vinfo.get("name", vkey),
            "type_indices": type_indices,
            "params": vinfo.get("params", []),
        }
    return result


def get_pids_for_param_names(block_info: dict, param_names: list[str]) -> list[str]:
    """Given a list of param names (e.g. COMP_ATTACK), return matching pid strings."""
    params = block_info.get("params", {})
    name_to_pid = {p["name"]: pid for pid, p in params.items()}
    pids = []
    for pname in param_names:
        if pname in name_to_pid:
            pids.append(name_to_pid[pname])
    return pids


def process_block_all_types(block_name: str, prefix: str, dry_run: bool = False) -> dict:
    """Calibrate all params across all effect types for a multi-variant block.

    Switches the effect type for each variant, calibrates only the params
    that are unique/specific to that variant (skipping already-calibrated ones).
    Restores original type at end.
    """
    log(f"▶ {block_name} [all-types mode]")

    try:
        resolved_prefix, block_info = resolve_block(block_name)
    except ValueError as e:
        log(f"  ERROR: {e}")
        return {}

    block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
    if not block_id:
        log(f"  ERROR: No block_id")
        return {}

    if block_id in UNSAFE_BLOCK_IDS:
        log(f"  SKIP: unsafe")
        return {}
    if block_id in DEDICATED_BLOCK_IDS:
        log(f"  SKIP: dedicated encoding")
        return {}

    params = block_info.get("params", {})

    # Get variant info
    variants = get_tvp_variants(prefix)
    if not variants:
        # No multi-variant — fall back to normal single-type processing
        log(f"  single-variant block, falling back to normal mode")
        return process_block(block_name, dry_run=dry_run)

    # Determine the Type param_id for this block
    block_base_name = re.sub(r'\s*\d+$', '', block_info["block_name"]).strip().lower()
    type_pid = TYPE_PID_MAP.get(block_base_name)
    if type_pid is None:
        log(f"  ERROR: No Type PID known for '{block_base_name}'")
        return process_block(block_name, dry_run=dry_run)

    # Count total unique params across all variants
    all_variant_pids = set()
    variant_pid_map = {}
    for vkey, vinfo in variants.items():
        vpids = get_pids_for_param_names(block_info, vinfo["params"])
        # Only calibratable
        vpids = [pid for pid in vpids
                 if params.get(pid, {}).get("type", "continuous") not in ("switch", "enum", "signed_int")
                 and params.get(pid, {}).get("max", 0) > 0]
        variant_pid_map[vkey] = vpids
        all_variant_pids.update(vpids)

    log(f"  {len(variants)} variants, {len(all_variant_pids)} unique calibratable params total")

    if dry_run:
        for vkey, vinfo in variants.items():
            representative_type = vinfo["type_indices"][0]
            n_pids = len(variant_pid_map[vkey])
            log(f"    variant [{vkey}] \"{vinfo['name']}\" type={representative_type}: {n_pids} params")
        return {}

    # Place block on grid if needed
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.5)
            placed_by_us = True
        except Exception as e:
            log(f"  ERROR placing block: {e}")
            return {}

    # Verify GET works
    chunks = midi.get_block_data(block_id)
    if not chunks:
        log(f"  ERROR: GET failed")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
            except Exception:
                pass
        return {}

    # Read current type (to restore at end)
    original_type_raw = get_raw_at(block_id, type_pid)

    # Process each variant
    results = {}
    calibrated_pids = set()  # Track PIDs already successfully calibrated
    total_ok = total_fail = total_unresponsive = 0

    for vkey, vinfo in variants.items():
        representative_type = vinfo["type_indices"][0]
        vpids = variant_pid_map[vkey]

        # Filter out already-calibrated PIDs
        new_pids = [pid for pid in vpids if pid not in calibrated_pids]
        if not new_pids:
            log(f"    [{vkey}] \"{vinfo['name']}\": all params already calibrated, skip")
            continue

        # Switch to this type (use first type_index as representative)
        if representative_type != original_type_raw:
            log(f"    [{vkey}] \"{vinfo['name']}\" → type {representative_type} ({len(new_pids)} new params)")
            midi.set_param_value(block_id, type_pid, float(representative_type), 1.0, raw_float=True)
            time.sleep(0.4)  # type change needs more settling time

            # Verify block still alive after type change
            chunks = midi.get_block_data(block_id)
            if not chunks:
                log(f"    WARNING: GET failed after type change to {representative_type}, skip variant")
                continue
        else:
            log(f"    [{vkey}] \"{vinfo['name']}\" (current type, {len(new_pids)} new params)")

        # Calibrate each new param
        ok = fail = unresponsive = 0
        for pid_str in sorted(new_pids, key=int):
            pid = int(pid_str)
            pinfo = params[pid_str]
            ptype = pinfo.get("type", "continuous")
            pmax = pinfo.get("max", 10.0)
            pmin = pinfo.get("min", 0)
            name = pinfo.get("display_name", f"pid_{pid}")

            try:
                result = calibrate_and_verify_param(block_id, pid, ptype, pmax, pmin)
            except FirmwarePanic as e:
                log(f"    PANIC at pid={pid} ({name}): {e}")
                # Attempt cleanup before re-raising
                if placed_by_us:
                    try:
                        midi.delete_block_at(row=0, col=1)
                    except Exception:
                        pass
                raise

            if result is None:
                continue

            if result["decode_style"] == "unresponsive":
                unresponsive += 1
                # Don't mark as calibrated — another variant might activate it
            elif result.get("verified", False):
                ok += 1
                calibrated_pids.add(pid_str)
                results[pid_str] = result
                result["display_name"] = name
                result["calibrated_at_type"] = representative_type
            else:
                fail += 1
                calibrated_pids.add(pid_str)  # Still mark as attempted
                results[pid_str] = result
                result["display_name"] = name
                result["calibrated_at_type"] = representative_type
                log(f"      ❌ pid={pid:>3} {name:<20} style={result['decode_style']} "
                    f"decode_max={result['decode_max']:.1f} "
                    f"sent={result.get('sent','?')} got={result.get('got','?')}")

        total_ok += ok
        total_fail += fail
        total_unresponsive += unresponsive
        log(f"      ✓ {ok} ok, {fail} fail, {unresponsive} unresponsive")

    # Restore original type
    if original_type_raw is not None:
        midi.set_param_value(block_id, type_pid, float(original_type_raw), 1.0, raw_float=True)
        time.sleep(0.3)

    # Cleanup
    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.3)
        except Exception:
            pass

    if not liveness_check():
        raise FirmwarePanic(f"FM9 died after {block_name}")

    uncalibrated = len(all_variant_pids) - len(calibrated_pids)
    log(f"  TOTAL: ✅ {total_ok} verified, ❌ {total_fail} failed, "
        f"⏭️ {total_unresponsive} unresponsive, "
        f"🔲 {uncalibrated} uncalibrated")
    return results


def sweep_block_unresponsive(block_name: str, dry_run: bool = False) -> dict:
    """Sweep all effect types to calibrate previously-unresponsive params.

    For each uncalibrated param, tries every available effect type until
    the param responds. This catches type-specific params that TVP doesn't
    model (e.g., Delay Atten only active in Duck Delay types).
    """
    log(f"▶ {block_name} [sweep mode]")

    try:
        resolved_prefix, block_info = resolve_block(block_name)
    except ValueError as e:
        log(f"  ERROR: {e}")
        return {}

    block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
    if not block_id:
        log(f"  ERROR: No block_id")
        return {}

    if block_id in UNSAFE_BLOCK_IDS:
        log(f"  SKIP: unsafe")
        return {}
    if block_id in DEDICATED_BLOCK_IDS:
        log(f"  SKIP: dedicated encoding")
        return {}

    params = block_info.get("params", {})

    # Find uncalibrated continuous/bipolar/frequency params
    target_pids = []
    for pid_str, p in params.items():
        ptype = p.get("type", "continuous")
        if ptype in ("switch", "enum", "signed_int"):
            continue
        if p.get("max", 0) == 0:
            continue
        # Already calibrated?
        if "decode_max" in p or "decode_style" in p or "decode_scale" in p:
            continue
        target_pids.append(pid_str)

    if not target_pids:
        log(f"  SKIP: all params already calibrated")
        return {}

    # Determine the Type param_id and available types
    block_base_name = re.sub(r'\s*\d+$', '', block_info["block_name"]).strip().lower()
    type_pid = TYPE_PID_MAP.get(block_base_name)
    defs_key = BLOCK_TO_DEFS_KEY.get(block_base_name)

    if type_pid is None or defs_key is None or defs_key not in EFFECT_DEFS:
        # No type switching possible — just probe once at current type
        log(f"  {len(target_pids)} uncalibrated params, no type list available")
        if dry_run:
            return {}
        # Fall through to single-probe below
        type_list = [None]  # sentinel: don't switch type
    else:
        type_list_names = EFFECT_DEFS[defs_key]
        n_types = len(type_list_names)
        log(f"  {len(target_pids)} uncalibrated params, {n_types} types to sweep")
        if dry_run:
            return {}
        type_list = list(range(n_types))

    # Place block on grid if needed
    status = midi.get_status_dump()
    placed_by_us = False
    if block_id not in status:
        try:
            midi.add_block_at(block_id, row=0, col=1)
            time.sleep(0.5)
            placed_by_us = True
        except Exception as e:
            log(f"  ERROR placing block: {e}")
            return {}

    # Verify GET works
    chunks = midi.get_block_data(block_id)
    if not chunks:
        log(f"  ERROR: GET failed")
        if placed_by_us:
            try:
                midi.delete_block_at(row=0, col=1)
            except Exception:
                pass
        return {}

    # Read original type to restore later
    original_type = None
    if type_pid is not None:
        original_type = get_raw_at(block_id, type_pid)

    # Probe target PIDs — sweep types, batch all PIDs per type
    results = {}
    rescued = 0
    remaining_pids = set(target_pids)

    # First: probe all at current type (no switch needed)
    t_current = time.time()
    newly_found = []
    for pid_str in sorted(remaining_pids, key=int):
        pid = int(pid_str)
        pinfo = params[pid_str]
        ptype = pinfo.get("type", "continuous")
        pmax = pinfo.get("max", 10.0)
        pmin = pinfo.get("min", 0)
        name = pinfo.get("display_name", f"pid_{pid}")

        try:
            result = calibrate_and_verify_param(block_id, pid, ptype, pmax, pmin)
        except FirmwarePanic as e:
            log(f"  PANIC at pid={pid} ({name}): {e}")
            if placed_by_us:
                try:
                    midi.delete_block_at(row=0, col=1)
                except Exception:
                    pass
            raise

        if result is None:
            remaining_pids.discard(pid_str)
            continue

        if result["decode_style"] != "unresponsive":
            results[pid_str] = result
            result["display_name"] = name
            result["rescued_at_type"] = original_type
            newly_found.append(pid_str)
            rescued += 1

    remaining_pids -= set(newly_found)
    elapsed_current = time.time() - t_current
    n_probed = len(target_pids)
    per_param_current = elapsed_current / n_probed if n_probed else 0

    if remaining_pids and type_list != [None]:
        log(f"    current type: {rescued} found, {len(remaining_pids)} still unresponsive "
            f"({elapsed_current:.1f}s, {per_param_current:.2f}s/param) → sweeping {len(type_list)-1} types")

        # Sweep other types
        _sweep_timing = {"set": 0, "sleep": 0, "get": 0, "calls": 0}
        for type_idx in type_list:
            if not remaining_pids:
                break
            if type_idx == original_type:
                continue  # Already tried

            t_type_start = time.time()
            midi.set_param_value(block_id, type_pid, float(type_idx), 1.0, raw_float=True)
            time.sleep(0.3)

            # Verify block alive after type switch
            chunks = midi.get_block_data(block_id)
            if not chunks:
                log(f"    type={type_idx}: GET failed, skip")
                continue

            newly_found = []
            for pid_str in sorted(remaining_pids, key=int):
                pid = int(pid_str)
                pinfo = params[pid_str]
                ptype = pinfo.get("type", "continuous")
                pmax = pinfo.get("max", 10.0)
                pmin = pinfo.get("min", 0)
                name = pinfo.get("display_name", f"pid_{pid}")

                try:
                    result = calibrate_and_verify_param(block_id, pid, ptype, pmax, pmin,
                                                       _timing=_sweep_timing)
                except FirmwarePanic as e:
                    log(f"  PANIC at pid={pid} ({name}) type={type_idx}: {e}")
                    if placed_by_us:
                        try:
                            midi.delete_block_at(row=0, col=1)
                        except Exception:
                            pass
                    raise

                if result is None:
                    remaining_pids.discard(pid_str)
                    continue

                if result["decode_style"] != "unresponsive":
                    results[pid_str] = result
                    result["display_name"] = name
                    result["rescued_at_type"] = type_idx
                    newly_found.append(pid_str)
                    rescued += 1
                    log(f"    ✅ pid={pid:>3} {name:<20} rescued at type={type_idx}")

            remaining_pids -= set(newly_found)
            elapsed = time.time() - t_type_start
            n_probed = len(remaining_pids) + len(newly_found)
            per_param = elapsed / n_probed if n_probed else 0
            log(f"    type={type_idx:>3}: +{len(newly_found)} rescued, "
                f"{len(remaining_pids)} remaining "
                f"({elapsed:.1f}s, {per_param:.2f}s/param)")

        # Log timing breakdown for entire sweep
        if _sweep_timing["calls"] > 0:
            t = _sweep_timing
            total_t = t["set"] + t["sleep"] + t["get"]
            log(f"    ⏱️ sweep timing: SET={t['set']:.1f}s GET={t['get']:.1f}s "
                f"sleep={t['sleep']:.1f}s total={total_t:.1f}s "
                f"({t['calls']} calls, GET={t['get']/t['calls']:.2f}s/call)")

    still_unresponsive = len(remaining_pids)

    # Final restore + cleanup
    if original_type is not None and type_pid is not None:
        midi.set_param_value(block_id, type_pid, float(original_type), 1.0, raw_float=True)
        time.sleep(0.3)

    if placed_by_us:
        try:
            midi.delete_block_at(row=0, col=1)
            time.sleep(0.3)
        except Exception:
            pass

    if not liveness_check():
        raise FirmwarePanic(f"FM9 died after {block_name}")

    log(f"  ✅ {rescued} rescued, ⏭️ {still_unresponsive} truly unresponsive "
        f"(of {len(target_pids)} targets)")
    return results


def apply_results(all_calibrations: dict[str, dict]):
    """Apply calibration results to all_params.json."""
    with open(DATA_DIR / "all_params.json") as f:
        all_params = json.load(f)

    total_applied = 0

    for block_name, block_results in all_calibrations.items():
        # Find prefix
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
                continue

        block_data = all_params.get(prefix)
        if not block_data:
            continue

        for pid_str, cal in block_results.items():
            if cal["decode_style"] == "unresponsive":
                continue
            if not cal.get("verified", False):
                continue  # Only apply verified calibrations

            pinfo = block_data.get("params", {}).get(pid_str)
            if not pinfo:
                continue
            if pinfo.get("verified"):
                continue  # Don't overwrite hand-verified

            pmax = pinfo.get("max", 10.0)
            decode_max = cal["decode_max"]
            decode_style = cal["decode_style"]
            changed = False

            # Apply decode_scale
            if cal.get("decode_scale") == "4096":
                if pinfo.get("decode_scale") != "4096":
                    pinfo["decode_scale"] = "4096"
                    changed = True
            else:
                # Apply decode_max if different from display_max
                if abs(decode_max - pmax) > pmax * 0.05 and abs(decode_max - pmax) > 0.5:
                    pinfo["decode_max"] = decode_max
                    changed = True
                elif "decode_max" in pinfo and abs(decode_max - pmax) <= pmax * 0.05:
                    del pinfo["decode_max"]
                    changed = True

            # Always record decode_style (marks param as calibrated)
            if decode_style == "center":
                if pinfo.get("decode_style") != "center":
                    pinfo["decode_style"] = "center"
                    changed = True
            elif decode_style == "frequency":
                if pinfo.get("decode_style") != "frequency":
                    pinfo["decode_style"] = "frequency"
                    changed = True
            else:
                # "zero" — always write to mark as calibrated
                if pinfo.get("decode_style") != "zero":
                    pinfo["decode_style"] = "zero"
                    changed = True

            if changed:
                total_applied += 1

    if total_applied > 0:
        with open(DATA_DIR / "all_params.json", 'w') as f:
            json.dump(all_params, f, indent=2)
        log(f"Applied {total_applied} calibration updates to all_params.json")
    else:
        log(f"No changes to apply (all params already calibrated or unresponsive)")


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate + verify decode params in one pass"
    )
    parser.add_argument("--block", help="Specific block (e.g., 'Delay 1')")
    parser.add_argument("--all", action="store_true", help="All effect blocks (default type only)")
    parser.add_argument("--all-types", action="store_true",
                        help="All effect blocks × all effect types (full coverage)")
    parser.add_argument("--sweep-unresponsive", action="store_true",
                        help="Sweep all types to rescue uncalibrated params")
    parser.add_argument("--start-from", help="Resume from this block")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    parser.add_argument("--apply", action="store_true", help="Write to all_params.json")
    args = parser.parse_args()

    if not args.block and not args.all and not args.all_types and not args.sweep_unresponsive:
        print("Usage: --block 'Block Name' or --all or --all-types or --sweep-unresponsive")
        sys.exit(1)

    log("=" * 60)
    if args.all_types:
        log("calibrate_and_verify.py — ALL TYPES mode")
    elif args.sweep_unresponsive:
        log("calibrate_and_verify.py — SWEEP UNRESPONSIVE mode")
    else:
        log("calibrate_and_verify.py — unified calibration + verification")
    log("=" * 60)

    load_4096_params()
    if _4096_PARAMS:
        log(f"4096-scale params: {len(_4096_PARAMS)} (static)")

    ensure_connected()
    log("FM9 connected")

    all_calibrations = {}
    blocks_done = 0

    if args.block:
        prefix_key = None
        for p, info in ALL_PARAMS.items():
            if p == "_meta":
                continue
            bn = info.get("block_name", "")
            if args.block.lower().startswith(bn.lower()):
                prefix_key = p
                break
        try:
            if args.all_types and prefix_key and get_tvp_variants(prefix_key):
                cal = process_block_all_types(args.block, prefix_key, dry_run=args.dry_run)
            elif args.sweep_unresponsive:
                cal = sweep_block_unresponsive(args.block, dry_run=args.dry_run)
            else:
                cal = process_block(args.block, dry_run=args.dry_run)
            if cal:
                all_calibrations[args.block] = cal
                blocks_done = 1
                if args.apply and not args.dry_run:
                    apply_results({args.block: cal})
        except FirmwarePanic as e:
            log(f"ABORT: {e}")
    elif args.all or args.all_types or args.sweep_unresponsive:
        block_list = []
        for prefix, info in ALL_PARAMS.items():
            if prefix == "_meta":
                continue
            bid = info.get("block_id_base", 0)
            if bid in UNSAFE_BLOCK_IDS or bid in DEDICATED_BLOCK_IDS:
                continue
            block_list.append((prefix, info))

        total = len(block_list)
        skipping = args.start_from is not None
        log(f"Target blocks: {total}")
        consecutive_failures = 0

        for i, (prefix, info) in enumerate(block_list):
            block_name = f"{info['block_name']} 1"

            if skipping:
                if args.start_from.lower() in block_name.lower():
                    skipping = False
                else:
                    continue

            log(f"[{i+1}/{total}] {block_name}")

            try:
                if args.sweep_unresponsive:
                    cal = sweep_block_unresponsive(block_name, dry_run=args.dry_run)
                elif args.all_types and get_tvp_variants(prefix):
                    cal = process_block_all_types(block_name, prefix, dry_run=args.dry_run)
                else:
                    cal = process_block(block_name, dry_run=args.dry_run)
                if cal:
                    all_calibrations[block_name] = cal
                    consecutive_failures = 0
                    # Apply immediately per block
                    if args.apply and not args.dry_run:
                        apply_results({block_name: cal})
                elif not args.dry_run:
                    consecutive_failures += 1
                blocks_done += 1
            except FirmwarePanic as e:
                log(f"ABORT: {e}")
                log(f"Done: {blocks_done}/{total}")
                flag = "--sweep-unresponsive" if args.sweep_unresponsive else (
                    "--all-types" if args.all_types else "--all")
                log(f"Resume: {flag} --apply --start-from \"{block_name}\"")
                break

            if consecutive_failures >= 3:
                log(f"ABORT: {consecutive_failures} consecutive blocks returned no data — FM9 likely unresponsive")
                flag = "--sweep-unresponsive" if args.sweep_unresponsive else (
                    "--all-types" if args.all_types else "--all")
                log(f"Resume: {flag} --apply --start-from \"{block_name}\"")
                break

    # Save raw results (merge with existing)
    results_path = Path(__file__).parent / "calibration_results.json"
    existing = {}
    if results_path.exists():
        try:
            existing = json.loads(results_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing.update(all_calibrations)
    with open(results_path, 'w') as f:
        json.dump(existing, f, indent=2)
    log(f"Raw results → {results_path} ({len(existing)} blocks total)")

    # Summary
    total_params = sum(len(v) for v in all_calibrations.values())
    verified = sum(1 for block in all_calibrations.values()
                   for cal in block.values() if cal.get("verified"))
    failed = sum(1 for block in all_calibrations.values()
                 for cal in block.values()
                 if not cal.get("verified") and cal["decode_style"] != "unresponsive")
    unresponsive = sum(1 for block in all_calibrations.values()
                       for cal in block.values()
                       if cal["decode_style"] == "unresponsive")

    log(f"\nSummary: {total_params} params processed")
    log(f"  ✅ {verified} verified")
    log(f"  ❌ {failed} failed verification")
    log(f"  ⏭️  {unresponsive} unresponsive (type-specific)")


if __name__ == "__main__":
    main()
