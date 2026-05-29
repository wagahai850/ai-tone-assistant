"""Shared utilities and state for FM9 MCP tools."""

import json
import sys
from pathlib import Path
from typing import Any

from fractal_midi import FractalMidi, DEVICES

# --- Device Selection (from CLI args) ---

DEVICE_KEY = "fm9"  # default
for i, arg in enumerate(sys.argv):
    if arg == "--device" and i + 1 < len(sys.argv):
        DEVICE_KEY = sys.argv[i + 1]

if DEVICE_KEY not in DEVICES:
    print(f"Unknown device '{DEVICE_KEY}'. Available: {list(DEVICES.keys())}", file=sys.stderr)
    sys.exit(1)

DEVICE = DEVICES[DEVICE_KEY]

# --- Data Loading ---

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "fm9"


def load_json(filename: str) -> dict:
    with open(DATA_DIR / filename, "r") as f:
        return json.load(f)


# --- Loaded Data ---

AMP_TYPES: dict[str, str] = load_json("amp_types.json")
DRIVE_TYPES: dict[str, str] = load_json("drive_types.json")
ALL_PARAMS: dict = load_json("all_params.json")
EFFECT_DEFS: dict = load_json("effect_definitions.json")
TYPE_VALID_PARAMS: dict = load_json("type_valid_params.json")
WIKI_MODELS: dict = load_json("wiki_models.json")
WIKI_BLOCKS: dict = load_json("wiki_blocks.json")

# --- Reverse Lookups ---

AMP_NAME_TO_ID: dict[str, int] = {}
for id_str, name in AMP_TYPES.items():
    if name not in AMP_NAME_TO_ID:
        AMP_NAME_TO_ID[name] = int(id_str)

DRIVE_NAME_TO_ID: dict[str, int] = {}
for id_str, name in DRIVE_TYPES.items():
    if name not in DRIVE_NAME_TO_ID:
        DRIVE_NAME_TO_ID[name] = int(id_str)

# --- Block ID constants from ALL_PARAMS ---

AMP_BLOCK_ID_BASE = ALL_PARAMS["DISTORT"]["block_id_base"]
DRIVE_BLOCK_ID_BASE = ALL_PARAMS["FUZZ"]["block_id_base"]

# --- Build block_id → name map from ALL_PARAMS ---
# Replaces the old BLOCKS dict. Generates all instances for each prefix.

BLOCK_ID_TO_NAME: dict[int, str] = {}
BLOCK_NAME_TO_ID: dict[str, int] = {}

for prefix, info in ALL_PARAMS.items():
    if prefix == "_meta":
        continue
    block_name = info["block_name"]
    base_id = info["block_id_base"]
    max_inst = info["max_instances"]
    for i in range(max_inst):
        bid = base_id + i
        instance_name = f"{block_name} {i + 1}"
        BLOCK_ID_TO_NAME[bid] = instance_name
        BLOCK_NAME_TO_ID[instance_name] = bid

# Blocks known to exist on device but not yet in all_params.json
_EXTRA_BLOCKS = {
    "Gate/Expander": (0x92, 4),
    "Filter": (0x72, 4),
}
for block_name, (base_id, max_inst) in _EXTRA_BLOCKS.items():
    for i in range(max_inst):
        bid = base_id + i
        instance_name = f"{block_name} {i + 1}"
        if bid not in BLOCK_ID_TO_NAME:
            BLOCK_ID_TO_NAME[bid] = instance_name
            BLOCK_NAME_TO_ID[instance_name] = bid

# Block name -> prefix key in ALL_PARAMS
BLOCK_NAME_TO_PREFIX: dict[str, str] = {}
for prefix, info in ALL_PARAMS.items():
    if prefix == "_meta":
        continue
    BLOCK_NAME_TO_PREFIX[info["block_name"].lower()] = prefix
    short = info["block_name"].replace(" 1", "").lower()
    if short not in BLOCK_NAME_TO_PREFIX:
        BLOCK_NAME_TO_PREFIX[short] = prefix

# --- MIDI Singleton ---

midi = FractalMidi()
midi.configure(DEVICE_KEY)


def ensure_connected():
    """Ensure MIDI connection is established. Auto-reconnects on failure."""
    if not midi.connected:
        midi.connect()
    else:
        try:
            import mido as _mido
            with midi._midi_lock:
                midi._outport.send(
                    _mido.Message("sysex", data=[0x00, 0x01, 0x74, midi.model_id, 0x13, 0x04])
                )
        except Exception:
            try:
                midi.disconnect()
            except Exception:
                pass
            midi._outport = None
            midi._inport = None
            midi.connect()


# --- Encoding Helpers ---


def encode_param(display_value: float, display_max: float) -> list[int]:
    """Encode display value to 3-byte Fractal format (21-bit, 7-bit packed)."""
    full_value = int(round(display_value / display_max * 65534))
    full_value = max(0, min(65534, full_value))
    return [full_value & 0x7F, (full_value >> 7) & 0x7F, (full_value >> 14) & 0x7F]


def decode_param(lo: int, hi: int, msb: int, display_max: float) -> float:
    """Decode 3-byte Fractal format to display value."""
    raw = lo | (hi << 7) | (msb << 14)
    return round(raw / 65534 * display_max, 2)


def encode_bipolar(display_value: float, display_max: float) -> list[int]:
    """Encode bipolar value (e.g., ±20dB where display_max=20.0)."""
    half_max = display_max
    raw = int(round((display_value + half_max) / (2 * half_max) * 65534))
    raw = max(0, min(65534, raw))
    return [raw & 0x7F, (raw >> 7) & 0x7F, (raw >> 14) & 0x7F]


def decode_bipolar(lo: int, hi: int, msb: int, display_max: float, display_min: float | None = None) -> float:
    """Decode bipolar 3-byte value.

    Args:
        display_max: Maximum display value (e.g., 10.0 for -10 to +10)
        display_min: Minimum display value. If None, assumes symmetric (-display_max).
                     For asymmetric ranges (e.g., Level -80 to +20), pass both.
    """
    raw = lo | (hi << 7) | (msb << 14)
    if display_min is None:
        display_min = -display_max
    total_range = display_max - display_min
    return round(raw / 65534 * total_range + display_min, 2)


def encode_switch(value: bool) -> list[int]:
    """Encode switch (ON/OFF)."""
    return [int(value), 0, 0]


def decode_switch(lo: int, hi: int, msb: int) -> bool:
    """Decode switch value."""
    return lo != 0


def recalc_checksum(chunk: list[int]) -> list[int]:
    """Recalculate checksum for a chunk (mido data format, no F0/F7)."""
    cs = 0
    for b in chunk[3:-1]:
        cs ^= b
    chunk[-1] = (cs ^ 0x05) & 0x7F
    return chunk


# --- Block Resolution Helpers ---


def resolve_block(block_str: str) -> tuple[str, dict]:
    """Resolve a block name or hex ID to (prefix, block_info).

    Supports instance 2+ blocks (e.g., "Delay 2") by looking up the base prefix
    and returning a modified block_info with the correct block_id for that instance.

    Accepts: "Amp 1", "Delay 2", "0x3A", "0x47", etc.
    """
    import re

    # Try hex ID first
    if block_str.startswith("0x") or block_str.startswith("0X"):
        bid_int = int(block_str, 16)
        # Find which prefix owns this block_id
        for prefix, info in ALL_PARAMS.items():
            if prefix == "_meta":
                continue
            base = info["block_id_base"]
            max_inst = info["max_instances"]
            if base <= bid_int < base + max_inst:
                instance = bid_int - base  # 0-indexed
                instance_name = f"{info['block_name']} {instance + 1}"
                modified = dict(info)
                modified["_instance"] = instance
                modified["_block_id_int"] = bid_int
                modified["block_name"] = instance_name
                return prefix, modified
        raise ValueError(f"No block with ID {block_str}")

    # Try exact match in BLOCK_NAME_TO_ID (handles "Delay 2", "Amp 1", etc.)
    if block_str in BLOCK_NAME_TO_ID:
        bid_int = BLOCK_NAME_TO_ID[block_str]
        # Find the prefix
        for prefix, info in ALL_PARAMS.items():
            if prefix == "_meta":
                continue
            base = info["block_id_base"]
            max_inst = info["max_instances"]
            if base <= bid_int < base + max_inst:
                instance = bid_int - base
                modified = dict(info)
                modified["_instance"] = instance
                modified["_block_id_int"] = bid_int
                modified["block_name"] = block_str
                return prefix, modified

    # Try case-insensitive match in BLOCK_NAME_TO_ID
    key = block_str.strip()
    key_lower = key.lower()
    for name, bid_int in BLOCK_NAME_TO_ID.items():
        if name.lower() == key_lower:
            for prefix, info in ALL_PARAMS.items():
                if prefix == "_meta":
                    continue
                base = info["block_id_base"]
                max_inst = info["max_instances"]
                if base <= bid_int < base + max_inst:
                    instance = bid_int - base
                    modified = dict(info)
                    modified["_instance"] = instance
                    modified["_block_id_int"] = bid_int
                    modified["block_name"] = name
                    return prefix, modified

    # Try name match in BLOCK_NAME_TO_PREFIX (e.g., "amp", "delay", "chorus")
    if key_lower in BLOCK_NAME_TO_PREFIX:
        prefix = BLOCK_NAME_TO_PREFIX[key_lower]
        info = ALL_PARAMS[prefix]
        modified = dict(info)
        modified["_instance"] = 0
        modified["_block_id_int"] = info["block_id_base"]
        modified["block_name"] = f"{info['block_name']} 1"
        return prefix, modified

    # Fuzzy: try partial match in BLOCK_NAME_TO_PREFIX
    for name, prefix in BLOCK_NAME_TO_PREFIX.items():
        if key_lower in name or name in key_lower:
            info = ALL_PARAMS[prefix]
            modified = dict(info)
            modified["_instance"] = 0
            modified["_block_id_int"] = info["block_id_base"]
            modified["block_name"] = f"{info['block_name']} 1"
            return prefix, modified

    available = sorted(set(info["block_name"] for p, info in ALL_PARAMS.items() if p != "_meta"))
    raise ValueError(f"Unknown block '{block_str}'. Available: {available}")


def resolve_param(block_info: dict, param_name: str) -> tuple[int, str]:
    """Resolve a parameter name to (param_id, internal_name)."""
    params = block_info["params"]

    for pid_str, pinfo in params.items():
        if pinfo["display_name"].lower() == param_name.lower():
            return int(pid_str), pinfo["name"]

    for pid_str, pinfo in params.items():
        short_internal = pinfo["name"].split("_", 1)[-1] if "_" in pinfo["name"] else pinfo["name"]
        if short_internal.lower() == param_name.lower():
            return int(pid_str), pinfo["name"]

    for pid_str, pinfo in params.items():
        if param_name.lower() in pinfo["display_name"].lower():
            return int(pid_str), pinfo["name"]

    available = sorted(pinfo["display_name"] for pinfo in params.values())
    raise ValueError(f"Unknown parameter '{param_name}'. Available: {available[:20]}...")


def resolve_block_id(block: str) -> int:
    """Resolve block name/hex to integer block_id.

    Accepts: "Amp 1", "Drive 2", "0x3A", etc.
    """
    # Hex ID
    if block.startswith("0x") or block.startswith("0X"):
        return int(block, 16)

    # Exact match in BLOCK_NAME_TO_ID
    if block in BLOCK_NAME_TO_ID:
        return BLOCK_NAME_TO_ID[block]

    # Case-insensitive match
    key_lower = block.lower().strip()
    for name, bid in BLOCK_NAME_TO_ID.items():
        if name.lower() == key_lower:
            return bid

    raise ValueError(f"Unknown block '{block}'. Known: {sorted(BLOCK_NAME_TO_ID.keys())}")
