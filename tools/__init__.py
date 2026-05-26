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
AMP_PARAMS: dict = load_json("amp_params.json")
DRIVE_PARAMS: dict = load_json("drive_params.json")
BLOCKS: dict = load_json("blocks.json")
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

# Block IDs
AMP1_BLOCK_ID = AMP_PARAMS["block_id_int"]
DRIVE1_BLOCK_ID = DRIVE_PARAMS["block_id_int"]

# Block name -> prefix key in ALL_PARAMS
BLOCK_NAME_TO_PREFIX: dict[str, str] = {}
for prefix, info in ALL_PARAMS.items():
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


def decode_bipolar(lo: int, hi: int, msb: int, display_max: float) -> float:
    """Decode bipolar 3-byte value."""
    raw = lo | (hi << 7) | (msb << 14)
    half_max = display_max
    return round(raw / 65534 * (2 * half_max) - half_max, 2)


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

    Supports instance 2+ blocks (e.g., "Delay 2") by looking up BLOCKS
    for the block_id and using instance 1's param definitions.
    """
    # Try hex ID first
    if block_str.startswith("0x") or block_str.startswith("0X"):
        hex_id = block_str.upper()
        for prefix, info in ALL_PARAMS.items():
            if info.get("block_id") == hex_id:
                return prefix, info
        # Check BLOCKS for instance 2+ (hex match)
        bid_int = int(block_str, 16)
        for bname, binfo in BLOCKS.items():
            if binfo["block_id_int"] == bid_int:
                # Find the instance 1 prefix by stripping instance number
                return _find_instance1_prefix(bname, bid_int)
        raise ValueError(f"No block with ID {block_str}")

    # Try exact match in BLOCKS first (handles "Delay 2", "Reverb 2", etc.)
    if block_str in BLOCKS:
        binfo = BLOCKS[block_str]
        bid_int = binfo["block_id_int"]
        return _find_instance1_prefix(block_str, bid_int)

    # Try name match in ALL_PARAMS (case-insensitive)
    key = block_str.lower().strip()
    if key in BLOCK_NAME_TO_PREFIX:
        prefix = BLOCK_NAME_TO_PREFIX[key]
        return prefix, ALL_PARAMS[prefix]

    # Try case-insensitive match in BLOCKS
    for bname, binfo in BLOCKS.items():
        if bname.lower() == key:
            bid_int = binfo["block_id_int"]
            return _find_instance1_prefix(bname, bid_int)

    # Fuzzy: try partial match in BLOCK_NAME_TO_PREFIX
    for name, prefix in BLOCK_NAME_TO_PREFIX.items():
        if key in name or name in key:
            return prefix, ALL_PARAMS[prefix]

    available = sorted(set(info["block_name"] for info in ALL_PARAMS.values()))
    raise ValueError(f"Unknown block '{block_str}'. Available: {available}")


def _find_instance1_prefix(block_name: str, block_id_int: int) -> tuple[str, dict]:
    """Given a block name (possibly instance 2+), return the instance 1 prefix
    and a modified block_info dict with the correct block_id."""
    import re
    # Strip instance number to find base name: "Delay 2" -> "Delay", "Amp 1" -> "Amp"
    base = re.sub(r'\s*\d+$', '', block_name).strip().lower()

    # Find matching prefix in ALL_PARAMS
    for prefix, info in ALL_PARAMS.items():
        info_base = re.sub(r'\s*\d+$', '', info["block_name"]).strip().lower()
        if info_base == base:
            # Return a copy with the correct block_id for this instance
            modified = dict(info)
            modified["block_id"] = f"0x{block_id_int:02X}"
            modified["block_name"] = block_name
            return prefix, modified

    # Fallback: return first match from BLOCK_NAME_TO_PREFIX
    if base in BLOCK_NAME_TO_PREFIX:
        prefix = BLOCK_NAME_TO_PREFIX[base]
        info = ALL_PARAMS[prefix]
        modified = dict(info)
        modified["block_id"] = f"0x{block_id_int:02X}"
        modified["block_name"] = block_name
        return prefix, modified

    raise ValueError(f"Cannot resolve instance 1 params for '{block_name}'.")


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
    """Resolve block name/hex to integer block_id using BLOCKS map."""
    block_map = {name: v["block_id_int"] for name, v in BLOCKS.items()}
    block_map["Input 1"] = 0x25
    block_map["Output 1"] = 0x2A
    if block in block_map:
        return block_map[block]
    elif block.startswith("0x"):
        return int(block, 16)
    else:
        raise ValueError(f"Unknown block '{block}'. Known: {list(block_map.keys())}")
