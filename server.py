"""Fractal Audio Tone Assistant — MCP Server for FM9 / Axe-Fx III control."""

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from fm9_midi import FractalMidi, DEVICES

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

BASE_DIR = Path(__file__).parent


def load_json(filename: str) -> dict:
    with open(BASE_DIR / filename, "r") as f:
        return json.load(f)


AMP_TYPES: dict[str, str] = load_json("fm9_amp_types.json")
DRIVE_TYPES: dict[str, str] = load_json("fm9_drive_types.json")
AMP_PARAMS: dict = load_json("fm9_amp_params.json")
DRIVE_PARAMS: dict = load_json("fm9_drive_params.json")
BLOCKS: dict = load_json("fm9_blocks.json")

# Build reverse lookup: name -> id (use first occurrence for duplicates)
AMP_NAME_TO_ID: dict[str, int] = {}
for id_str, name in AMP_TYPES.items():
    if name not in AMP_NAME_TO_ID:
        AMP_NAME_TO_ID[name] = int(id_str)

DRIVE_NAME_TO_ID: dict[str, int] = {}
for id_str, name in DRIVE_TYPES.items():
    if name not in DRIVE_NAME_TO_ID:
        DRIVE_NAME_TO_ID[name] = int(id_str)

# Block IDs (shared across Fractal devices)
AMP1_BLOCK_ID = AMP_PARAMS["block_id_int"]
DRIVE1_BLOCK_ID = DRIVE_PARAMS["block_id_int"]


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


# --- MCP Server ---

mcp = FastMCP(
    f"{DEVICE.name} Tone Assistant",
    instructions=f"Control Fractal Audio {DEVICE.name} amp and drive parameters via USB MIDI SysEx.",
)

# Singleton MIDI connection
midi = FractalMidi()
midi.configure(DEVICE_KEY)


def ensure_connected():
    """Ensure MIDI connection is established. Auto-reconnects on failure."""
    if not midi.connected:
        midi.connect()
    else:
        # Test connection by trying a quick operation
        try:
            import mido as _mido
            # Send a harmless status query to verify port is alive
            with midi._midi_lock:
                midi._outport.send(_mido.Message("sysex", data=[0x00, 0x01, 0x74, midi.model_id, 0x13, 0x04]))
        except Exception:
            # Port is dead, reconnect
            try:
                midi.disconnect()
            except Exception:
                pass
            midi._outport = None
            midi._inport = None
            midi.connect()


# --- Tools ---

@mcp.tool()
def fm9_get_status() -> dict[str, Any]:
    """Get FM9 connection status and current block bypass states.

    Returns connection state and a map of effect blocks with their bypass/channel status.
    """
    try:
        ensure_connected()
        status = midi.get_status_dump()
        known_blocks = {v["block_id_int"]: name for name, v in BLOCKS.items()}
        named_status = {}
        for eid, info in status.items():
            name = known_blocks.get(eid, f"Block 0x{eid:02X}")
            named_status[name] = {
                "effect_id": eid,
                "bypassed": info["bypass"],
                "channel": info["channel"],
            }
        return {"connected": True, "device": DEVICE.name, "blocks": named_status}
    except Exception as e:
        return {"connected": False, "device": DEVICE.name, "error": str(e)}


@mcp.tool()
def fm9_list_amp_types(filter: str = "") -> dict[str, Any]:
    """List available FM9 Amp models.

    Args:
        filter: Optional search string to filter model names (case-insensitive).

    Returns a list of amp model names with their internal IDs.
    """
    results = {}
    for id_str, name in AMP_TYPES.items():
        if not filter or filter.lower() in name.lower():
            results[name] = int(id_str)
    unique = {}
    for name, id_val in sorted(results.items(), key=lambda x: x[0]):
        if name not in unique:
            unique[name] = id_val
    return {"count": len(unique), "models": unique}


@mcp.tool()
def fm9_list_drive_types(filter: str = "") -> dict[str, Any]:
    """List available FM9 Drive models.

    Args:
        filter: Optional search string to filter model names (case-insensitive).

    Returns a list of drive model names with their internal IDs.
    """
    results = {}
    for id_str, name in DRIVE_TYPES.items():
        if not filter or filter.lower() in name.lower():
            results[name] = int(id_str)
    unique = {}
    for name, id_val in sorted(results.items(), key=lambda x: x[0]):
        if name not in unique:
            unique[name] = id_val
    return {"count": len(unique), "models": unique}


@mcp.tool()
def fm9_set_amp_type(name: str) -> dict[str, Any]:
    """Set the Amp 1 model type by name.

    Args:
        name: Amp model name (e.g., "Brit 800 2204 High", "Plexi 50W High 1").
              Use fm9_list_amp_types to find available names.

    Returns success status and the model that was set.
    """
    try:
        ensure_connected()
        type_id = AMP_NAME_TO_ID.get(name)
        if type_id is None:
            for model_name, mid in AMP_NAME_TO_ID.items():
                if model_name.lower() == name.lower():
                    type_id = mid
                    name = model_name
                    break
        if type_id is None:
            matches = [(n, i) for n, i in AMP_NAME_TO_ID.items()
                       if name.lower() in n.lower()]
            if len(matches) == 1:
                name, type_id = matches[0]
            elif len(matches) > 1:
                return {
                    "success": False,
                    "error": f"Ambiguous name '{name}'. Matches: {[m[0] for m in matches[:10]]}",
                }
            else:
                return {"success": False, "error": f"Amp model '{name}' not found."}

        midi.set_amp_type(type_id, AMP1_BLOCK_ID)
        return {"success": True, "model": name, "type_id": type_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_drive_type(name: str) -> dict[str, Any]:
    """Set the Drive 1 model type by name.

    Args:
        name: Drive model name (e.g., "T808 Mod", "Klone Chiron").
              Use fm9_list_drive_types to find available names.

    Returns success status and the model that was set.
    """
    try:
        ensure_connected()
        type_id = DRIVE_NAME_TO_ID.get(name)
        if type_id is None:
            for model_name, mid in DRIVE_NAME_TO_ID.items():
                if model_name.lower() == name.lower():
                    type_id = mid
                    name = model_name
                    break
        if type_id is None:
            matches = [(n, i) for n, i in DRIVE_NAME_TO_ID.items()
                       if name.lower() in n.lower()]
            if len(matches) == 1:
                name, type_id = matches[0]
            elif len(matches) > 1:
                return {
                    "success": False,
                    "error": f"Ambiguous name '{name}'. Matches: {[m[0] for m in matches[:10]]}",
                }
            else:
                return {"success": False, "error": f"Drive model '{name}' not found."}

        chunks = midi.get_block_data(DRIVE1_BLOCK_ID)
        if not chunks:
            return {"success": False, "error": "Failed to get Drive 1 block data."}

        encoded = [type_id & 0x7F, (type_id >> 7) & 0x7F, (type_id >> 14) & 0x7F]
        chunks[0][7], chunks[0][8], chunks[0][9] = encoded
        chunks[0] = recalc_checksum(chunks[0])

        midi.put_block_data(DRIVE1_BLOCK_ID, chunks)
        return {"success": True, "model": name, "type_id": type_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_get_amp_params() -> dict[str, Any]:
    """Get current Amp 1 parameter values.

    Returns all mapped Amp 1 parameters with their current display values.
    """
    try:
        ensure_connected()
        chunks = midi.get_block_data(AMP1_BLOCK_ID)
        if not chunks:
            return {"success": False, "error": "Failed to get Amp 1 block data."}

        params = {}
        for name, info in AMP_PARAMS["params"].items():
            if info["type"] == "enum":
                continue
            start, end = info["offset"]
            lo, hi, msb = chunks[0][start], chunks[0][start + 1], chunks[0][start + 2]

            if info["type"] == "switch":
                params[name] = decode_switch(lo, hi, msb)
            elif info["type"] == "bipolar":
                params[name] = decode_bipolar(lo, hi, msb, info["max"])
            else:
                params[name] = decode_param(lo, hi, msb, info["max"])

        return {"success": True, "block": "Amp 1", "params": params}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_amp_params(params: dict[str, float | bool]) -> dict[str, Any]:
    """Set one or more Amp 1 parameters.

    Args:
        params: A dictionary of parameter name-value pairs. Available parameters:
            - "Treble Gain" (0-10, also known as Drive/Gain depending on model)
            - "Bass" (0-10)
            - "Mid" (0-10)
            - "Treble" (0-10)
            - "Master" (0-10)
            - "Depth" (0-10)
            - "Presence" (0-10)
            - "Normal Gain" (0-10)
            - "Level" (-20 to +20 dB)
            - "Bright" (true/false)
            - "Boost" (true/false)
            - "Cut" (true/false)
            - "Fat" (true/false)

    Example: fm9_set_amp_params(params={"Bass": 5.0, "Mid": 6.0, "Treble": 7.0})
    """
    try:
        ensure_connected()

        valid_params = {k: v for k, v in AMP_PARAMS["params"].items()
                        if v["type"] != "enum"}
        for key in params:
            if key not in valid_params:
                return {
                    "success": False,
                    "error": f"Unknown parameter '{key}'. Valid: {list(valid_params.keys())}",
                }

        chunks = midi.get_block_data(AMP1_BLOCK_ID)
        if not chunks:
            return {"success": False, "error": "Failed to get Amp 1 block data."}

        changes = {}
        for name, value in params.items():
            info = valid_params[name]
            start = info["offset"][0]

            if info["type"] == "switch":
                encoded = encode_switch(bool(value))
            elif info["type"] == "bipolar":
                encoded = encode_bipolar(float(value), info["max"])
            else:
                encoded = encode_param(float(value), info["max"])

            chunks[0][start], chunks[0][start + 1], chunks[0][start + 2] = encoded
            changes[name] = value

        chunks[0] = recalc_checksum(chunks[0])
        midi.put_block_data(AMP1_BLOCK_ID, chunks)
        midi.set_scene(0)

        return {"success": True, "block": "Amp 1", "changes": changes}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_get_drive_params() -> dict[str, Any]:
    """Get current Drive 1 parameter values.

    Returns all mapped Drive 1 parameters with their current display values.
    """
    try:
        ensure_connected()
        chunks = midi.get_block_data(DRIVE1_BLOCK_ID)
        if not chunks:
            return {"success": False, "error": "Failed to get Drive 1 block data."}

        params = {}
        for name, info in DRIVE_PARAMS["params"].items():
            if info["type"] == "enum":
                continue
            start = info["offset"][0]
            lo, hi, msb = chunks[0][start], chunks[0][start + 1], chunks[0][start + 2]

            if info["type"] == "switch":
                params[name] = decode_switch(lo, hi, msb)
            elif info["type"] == "bipolar":
                params[name] = decode_bipolar(lo, hi, msb, info["max"])
            else:
                params[name] = decode_param(lo, hi, msb, info["max"])

        return {"success": True, "block": "Drive 1", "params": params}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_drive_params(params: dict[str, float | bool]) -> dict[str, Any]:
    """Set one or more Drive 1 parameters.

    Args:
        params: A dictionary of parameter name-value pairs. Available parameters:
            - "Drive" (0-10)
            - "Tone" (0-10)
            - "Level" (0-10)
            - "Mix" (0-100%)
            - "Balance" (-100 to +100)

    Example: fm9_set_drive_params(params={"Drive": 6.0, "Tone": 5.5, "Level": 7.0})
    """
    try:
        ensure_connected()

        valid_params = {k: v for k, v in DRIVE_PARAMS["params"].items()
                        if v["type"] != "enum"}
        for key in params:
            if key not in valid_params:
                return {
                    "success": False,
                    "error": f"Unknown parameter '{key}'. Valid: {list(valid_params.keys())}",
                }

        chunks = midi.get_block_data(DRIVE1_BLOCK_ID)
        if not chunks:
            return {"success": False, "error": "Failed to get Drive 1 block data."}

        changes = {}
        for name, value in params.items():
            info = valid_params[name]
            start = info["offset"][0]

            if info["type"] == "switch":
                encoded = encode_switch(bool(value))
            elif info["type"] == "bipolar":
                encoded = encode_bipolar(float(value), info["max"])
            else:
                encoded = encode_param(float(value), info["max"])

            chunks[0][start], chunks[0][start + 1], chunks[0][start + 2] = encoded
            changes[name] = value

        chunks[0] = recalc_checksum(chunks[0])
        midi.put_block_data(DRIVE1_BLOCK_ID, chunks)
        midi.set_scene(0)

        return {"success": True, "block": "Drive 1", "changes": changes}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_scene(scene: int) -> dict[str, Any]:
    """Switch FM9 to a specific scene.

    Args:
        scene: Scene number (1-8).

    Returns success status.
    """
    try:
        ensure_connected()
        if not 1 <= scene <= 8:
            return {"success": False, "error": "Scene must be 1-8."}
        midi.set_scene(scene - 1)
        return {"success": True, "scene": scene}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_bypass(block: str, bypassed: bool) -> dict[str, Any]:
    """Set bypass state for an effect block.

    Args:
        block: Block name (e.g., "Amp 1", "Drive 1") or hex ID (e.g., "0x3A").
        bypassed: True to bypass (OFF), False to engage (ON).

    Returns success status.
    """
    try:
        ensure_connected()
        block_map = {name: v["block_id_int"] for name, v in BLOCKS.items()}
        block_map["Input 1"] = 0x25
        block_map["Output 1"] = 0x2A
        if block in block_map:
            effect_id = block_map[block]
        elif block.startswith("0x"):
            effect_id = int(block, 16)
        else:
            return {
                "success": False,
                "error": f"Unknown block '{block}'. Known: {list(block_map.keys())}",
            }

        midi.set_bypass(effect_id, bypassed)
        state = "bypassed" if bypassed else "engaged"
        return {"success": True, "block": block, "state": state}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_cab_ir(ir_id: int, block_id: str = "0x3E") -> dict[str, Any]:
    """Set Cab IR by numeric ID.

    Args:
        ir_id: The 21-bit IR identifier. Use fm9_read_param_raw with block 0x3E
               param_index 4 to read the current IR ID, or capture from Editor.
        block_id: Cab block ID as hex string (default "0x3E" = Cab 1).

    Returns success status. Note: IR IDs are not yet mapped to names.
    This is a low-level command for testing. IR ID mapping will be added later.
    """
    try:
        ensure_connected()
        bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
        midi.set_cab_ir(ir_id, bid)
        return {"success": True, "ir_id": ir_id, "block_id": block_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_channel(block: str, channel: str) -> dict[str, Any]:
    """Set the channel (A/B/C/D) for an effect block.

    Args:
        block: Block name (e.g., "Amp 1", "Cab 1") or hex ID (e.g., "0x3A").
        channel: Channel letter: "A", "B", "C", or "D".

    Returns success status.
    """
    try:
        ensure_connected()
        channel_map = {"A": 0, "B": 1, "C": 2, "D": 3}
        ch = channel_map.get(channel.upper())
        if ch is None:
            return {"success": False, "error": f"Invalid channel '{channel}'. Use A, B, C, or D."}

        block_map = {name: v["block_id_int"] for name, v in BLOCKS.items()}
        block_map["Input 1"] = 0x25
        block_map["Output 1"] = 0x2A
        if block in block_map:
            bid = block_map[block]
        elif block.startswith("0x"):
            bid = int(block, 16)
        else:
            return {
                "success": False,
                "error": f"Unknown block '{block}'. Known: {list(block_map.keys())}",
            }

        midi.set_channel(bid, ch)
        return {"success": True, "block": block, "channel": channel.upper()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_set_preset_name(name: str, preset_number: int = -1) -> dict[str, Any]:
    """Set the preset name for the current preset.

    Args:
        name: Preset name (max 32 ASCII characters).
        preset_number: Preset number (0-based). If -1, uses current preset from status.

    Returns success status.
    """
    try:
        ensure_connected()
        if preset_number < 0:
            return {"success": False, "error": "preset_number is required (0-based, e.g., 265)."}
        midi.set_preset_name(preset_number, name)
        return {"success": True, "name": name, "preset_number": preset_number}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_store_preset(preset_number: int) -> dict[str, Any]:
    """Store (save) the current preset state to flash.

    Args:
        preset_number: Preset number to store to (0-based, e.g., 265).

    Returns success status. This persists all current edits.
    """
    try:
        ensure_connected()
        midi.store_preset(preset_number)
        return {"success": True, "preset_number": preset_number}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_change_preset(preset_number: int) -> dict[str, Any]:
    """Switch to a different preset.

    Args:
        preset_number: Target preset number (0-based, e.g., 0 = first preset).

    Returns success status.
    """
    try:
        ensure_connected()
        midi.change_preset(preset_number)
        return {"success": True, "preset_number": preset_number}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Grid / Routing Tools ---

# Known block types for add_block (user-friendly names)
BLOCK_TYPE_MAP = {
    "Amp 1": 0x3A, "Amp1": 0x3A,
    "Amp 2": 0x3B, "Amp2": 0x3B,
    "Cab 1": 0x3E, "Cab1": 0x3E,
    "Cab 2": 0x3F, "Cab2": 0x3F,
    "Drive 1": 0x76, "Drive1": 0x76,
    "Drive 2": 0x77, "Drive2": 0x77,
    "Delay 1": 0x46, "Delay1": 0x46,
    "Delay 2": 0x47, "Delay2": 0x47,
    "Reverb 1": 0x42, "Reverb1": 0x42,
    "Reverb 2": 0x43, "Reverb2": 0x43,
    "Chorus 1": 0x4E, "Chorus1": 0x4E,
    "Chorus 2": 0x4F, "Chorus2": 0x4F,
    "Compressor 1": 0x52, "Comp1": 0x52, "Comp 1": 0x52,
    "Compressor 2": 0x53, "Comp2": 0x53, "Comp 2": 0x53,
    "GEQ": 0x32, "Graphic EQ": 0x32,
    "PEQ": 0x56, "Parametric EQ": 0x56,
    "Gate 1": 0x92, "Gate1": 0x92,
    "Gate 2": 0x93, "Gate2": 0x93,
    "Flanger 1": 0x62, "Flanger1": 0x62,
    "Flanger 2": 0x63, "Flanger2": 0x63,
    "Phaser 1": 0x66, "Phaser1": 0x66,
    "Phaser 2": 0x67, "Phaser2": 0x67,
    "Wah 1": 0x6A, "Wah1": 0x6A,
    "Wah 2": 0x6B, "Wah2": 0x6B,
    "Pitch 1": 0x6E, "Pitch1": 0x6E,
    "Pitch 2": 0x6F, "Pitch2": 0x6F,
    "Multidelay 1": 0x72, "Multidelay1": 0x72,
    "Multidelay 2": 0x73, "Multidelay2": 0x73,
    "Enhancer": 0x7A, "Enhance": 0x7A,
    "Tremolo 1": 0x5E, "Tremolo1": 0x5E,
    "Tremolo 2": 0x5F, "Tremolo2": 0x5F,
    "Rotary 1": 0x82, "Rotary1": 0x82,
    "Rotary 2": 0x83, "Rotary2": 0x83,
}


@mcp.tool()
def fm9_add_block(block_type: str, row: int, col: int) -> dict[str, Any]:
    """Add an effect block to the FM9 grid at a specific position.

    Args:
        block_type: Block type name (e.g., "Amp 1", "Drive 1", "Cab 1", "Delay 1",
                    "Reverb 1", "Chorus 1", "Comp 1", "GEQ", "Gate 1", "Flanger 1",
                    "Phaser 1", "Wah 1", "Pitch 1", "Enhancer", "Tremolo 1", "Rotary 1")
                    or hex ID (e.g., "0x3A").
        row: Grid row (1-5, displayed top to bottom).
        col: Grid column (1-14, displayed left to right).

    Returns success status with the grid position used.
    """
    try:
        ensure_connected()
        # Resolve block type
        if block_type.startswith("0x"):
            bid = int(block_type, 16)
        elif block_type in BLOCK_TYPE_MAP:
            bid = BLOCK_TYPE_MAP[block_type]
        else:
            # Case-insensitive search
            for name, block_id in BLOCK_TYPE_MAP.items():
                if name.lower() == block_type.lower():
                    bid = block_id
                    break
            else:
                return {
                    "success": False,
                    "error": f"Unknown block type '{block_type}'. Known: {sorted(set(BLOCK_TYPE_MAP.keys()))}",
                }

        # Validate grid bounds (user provides 1-based)
        if not (1 <= row <= 5):
            return {"success": False, "error": "Row must be 1-5."}
        if not (1 <= col <= 14):
            return {"success": False, "error": "Column must be 1-14."}

        # Convert to 0-based
        r = row - 1
        c = col - 1

        midi.add_block_at(bid, r, c)
        return {
            "success": True,
            "block_type": block_type,
            "block_id": f"0x{bid:02X}",
            "position": {"row": row, "col": col},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_delete_block(row: int, col: int) -> dict[str, Any]:
    """Delete the effect block at a specific grid position.

    Args:
        row: Grid row (1-5).
        col: Grid column (1-14).

    Returns success status.
    """
    try:
        ensure_connected()
        if not (1 <= row <= 5):
            return {"success": False, "error": "Row must be 1-5."}
        if not (1 <= col <= 14):
            return {"success": False, "error": "Column must be 1-14."}

        midi.delete_block_at(row - 1, col - 1)
        return {"success": True, "position": {"row": row, "col": col}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_move_block(from_row: int, from_col: int, to_row: int, to_col: int) -> dict[str, Any]:
    """Move an effect block from one grid position to another.

    Note: Moving a block disconnects any cables attached to it.

    Args:
        from_row: Source row (1-5).
        from_col: Source column (1-14).
        to_row: Destination row (1-5).
        to_col: Destination column (1-14).

    Returns success status.
    """
    try:
        ensure_connected()
        for label, val in [("from_row", from_row), ("to_row", to_row)]:
            if not (1 <= val <= 5):
                return {"success": False, "error": f"{label} must be 1-5."}
        for label, val in [("from_col", from_col), ("to_col", to_col)]:
            if not (1 <= val <= 14):
                return {"success": False, "error": f"{label} must be 1-14."}

        if from_row == to_row and from_col == to_col:
            return {"success": True, "message": "No movement needed."}

        midi.move_block(from_row - 1, from_col - 1, to_row - 1, to_col - 1)
        return {
            "success": True,
            "from": {"row": from_row, "col": from_col},
            "to": {"row": to_row, "col": to_col},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_connect_blocks(from_row: int, from_col: int, to_row: int, to_col: int) -> dict[str, Any]:
    """Connect two blocks with a cable. Shunt blocks are auto-placed in between.

    Both blocks must be on the same row. from_col must be less than to_col.
    Intermediate columns will have shunt (pass-through) blocks placed automatically.

    Args:
        from_row: Row of the source block (1-5).
        from_col: Column of the source block (1-14).
        to_row: Row of the destination block (must equal from_row).
        to_col: Column of the destination block (must be > from_col).

    Returns success status.
    """
    try:
        ensure_connected()
        if from_row != to_row:
            return {"success": False, "error": "Blocks must be on the same row for connection."}
        if not (1 <= from_row <= 5):
            return {"success": False, "error": "Row must be 1-5."}
        if not (1 <= from_col <= 14) or not (1 <= to_col <= 14):
            return {"success": False, "error": "Column must be 1-14."}
        if from_col >= to_col:
            return {"success": False, "error": "from_col must be less than to_col."}

        midi.connect_blocks(from_row - 1, from_col - 1, to_row - 1, to_col - 1)
        shunts = to_col - from_col - 1
        return {
            "success": True,
            "from": {"row": from_row, "col": from_col},
            "to": {"row": to_row, "col": to_col},
            "shunts_placed": shunts,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_disconnect_blocks(row: int, col: int) -> dict[str, Any]:
    """Disconnect (remove cable from) the block at the given position.

    Removes the cable going from this block to its right neighbor.

    Args:
        row: Row of the block (1-5).
        col: Column of the block whose right-side cable to remove (1-14).

    Returns success status.
    """
    try:
        ensure_connected()
        if not (1 <= row <= 5):
            return {"success": False, "error": "Row must be 1-5."}
        if not (1 <= col <= 14):
            return {"success": False, "error": "Column must be 1-14."}
        if col >= 14:
            return {"success": False, "error": "Cannot disconnect from last column."}

        r = row - 1
        c = col - 1
        midi.disconnect_adjacent(r, c, r, c + 1)
        return {"success": True, "position": {"row": row, "col": col}}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Diagnostic / RE Tools ---

@mcp.tool()
def fm9_get_block_data(block_id: str) -> dict[str, Any]:
    """Get raw block data via GET (func 0x1F) for any block ID.

    Args:
        block_id: Block ID as hex string (e.g., "0x3A" for Amp 1, "0x46" for Delay 1).

    Returns chunk count, sizes, and first 30 bytes of each chunk for inspection.
    Useful for reverse engineering parameter positions.
    """
    try:
        ensure_connected()
        bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
        chunks = midi.get_block_data(bid)
        if not chunks:
            return {"success": False, "error": f"No response from block {block_id}."}

        result = {
            "success": True,
            "block_id": block_id,
            "chunk_count": len(chunks),
            "chunks": [],
        }
        for i, chunk in enumerate(chunks):
            result["chunks"].append({
                "index": i,
                "size": len(chunk),
                "header": chunk[:10],
                "data_preview": chunk[7:37],  # first 30 bytes of payload
            })
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_read_param_raw(block_id: str, param_index: int) -> dict[str, Any]:
    """Read a raw 3-byte parameter value from a block at a given param index.

    Args:
        block_id: Block ID as hex string (e.g., "0x46").
        param_index: Parameter index (0-based). Offset = 7 + index * 3.

    Returns the raw 3 bytes and decoded values (continuous and bipolar interpretations).
    """
    try:
        ensure_connected()
        bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
        chunks = midi.get_block_data(bid)
        if not chunks:
            return {"success": False, "error": f"No response from block {block_id}."}

        offset = 7 + param_index * 3
        if offset + 2 >= len(chunks[0]):
            return {"success": False, "error": f"Param index {param_index} out of range (max {(len(chunks[0]) - 7) // 3 - 1})."}

        lo, hi, msb = chunks[0][offset], chunks[0][offset + 1], chunks[0][offset + 2]
        raw = lo | (hi << 7) | (msb << 14)

        return {
            "success": True,
            "block_id": block_id,
            "param_index": param_index,
            "offset": [offset, offset + 3],
            "raw_bytes": [lo, hi, msb],
            "raw_value": raw,
            "as_0_10": round(raw / 65534 * 10.0, 3),
            "as_0_100": round(raw / 65534 * 100.0, 3),
            "as_bipolar_20": round(raw / 65534 * 40.0 - 20.0, 3),
            "as_bipolar_100": round(raw / 65534 * 200.0 - 100.0, 3),
            "as_switch": lo != 0,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_dump_block_full(block_id: str) -> dict[str, Any]:
    """Dump full raw data of all chunks for a block. Returns complete byte arrays.

    Args:
        block_id: Block ID as hex string (e.g., "0x01" for preset meta, "0x3A" for Amp 1).

    Returns all chunks with their complete data as byte arrays.
    Useful for diffing block state before/after operations.
    """
    try:
        ensure_connected()
        bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
        chunks = midi.get_block_data(bid)
        if not chunks:
            return {"success": False, "error": f"No response from block {block_id}."}

        return {
            "success": True,
            "block_id": block_id,
            "chunk_count": len(chunks),
            "chunk_sizes": [len(c) for c in chunks],
            "chunks": chunks,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_send_raw_sysex(hex_bytes: str) -> dict[str, Any]:
    """Send a raw SysEx message and return the response. Lab/RE tool.

    Args:
        hex_bytes: Hex string of the FULL SysEx payload (without F0/F7).
                   Example: "00 01 74 12 01 35 00 00 00 00 00 01 00 00 00 00 00 00 02 00 03 03 00 20"
                   The tool will wrap it in F0...F7 and send via mido.

    Returns the first response message (if any) within 2 seconds.
    """
    try:
        ensure_connected()
        # Parse hex string
        hex_clean = hex_bytes.replace(" ", "").replace(",", "").replace("0x", "")
        if len(hex_clean) % 2 != 0:
            return {"success": False, "error": "Hex string must have even length."}
        data = [int(hex_clean[i:i+2], 16) for i in range(0, len(hex_clean), 2)]

        # Send
        import mido
        with midi._midi_lock:
            midi._flush_input()
            midi._outport.send(mido.Message("sysex", data=data))

            # Collect responses for 2 seconds
            import time
            time.sleep(0.5)
            responses = []
            deadline = time.time() + 1.5
            while time.time() < deadline:
                msg = midi._inport.poll()
                if msg is None:
                    if responses:
                        time.sleep(0.1)
                        msg = midi._inport.poll()
                        if msg is None:
                            break
                    else:
                        time.sleep(0.05)
                    continue
                if msg.type == "sysex":
                    responses.append(list(msg.data))
                    if len(responses) >= 10:
                        break

        return {
            "success": True,
            "sent_bytes": len(data),
            "sent_hex": " ".join(f"{b:02X}" for b in data),
            "response_count": len(responses),
            "responses": [
                {"len": len(r), "hex": " ".join(f"{b:02X}" for b in r[:30]) + ("..." if len(r) > 30 else "")}
                for r in responses[:5]
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Grid Reading Tool ---

@mcp.tool()
def fm9_read_grid() -> dict[str, Any]:
    """Read the current FM9 grid layout (which blocks are placed where).

    Returns a 5-row × 14-column grid showing block_id at each position.
    Empty cells have block_id = 0. Uses sub=0x2E SysEx query.

    The grid is returned as a dict with:
    - grid: 2D array [row][col] of block_ids
    - blocks: dict mapping "row,col" to block name (for non-empty cells)
    """
    try:
        ensure_connected()
        raw_grid = midi.read_grid_raw()

        # Get STATUS DUMP to resolve block_ids > 0x7F
        status = midi.get_status_dump()
        # Build lookup: low 7 bits -> full effect_id (for ids > 0x7F)
        high_id_lookup = {}
        for eid in status.keys():
            if eid > 0x7F:
                low7 = eid & 0x7F
                high_id_lookup[low7] = eid

        # Build simple grid (block_ids only) and block map
        known_blocks = {v["block_id_int"]: name for name, v in BLOCKS.items()}
        known_blocks[0x25] = "Input 1"
        known_blocks[0x2A] = "Output 1"

        grid = [[0] * 14 for _ in range(5)]
        block_map = {}

        for row in range(5):
            for col in range(14):
                cell = raw_grid[row][col]
                bid = cell["block_id"]
                # Resolve truncated block_ids (> 0x7F stored as low 7 bits)
                if bid != 0 and bid in high_id_lookup:
                    bid = high_id_lookup[bid]
                grid[row][col] = bid
                # Decode cable info from raw_32
                raw = cell["raw_32"]
                byte2 = (raw >> 16) & 0xFF
                byte3 = (raw >> 8) & 0xFF
                is_shunt = byte2 == 0x08
                cable_from = []
                for r in range(5):
                    if byte3 & (1 << (r + 1)):
                        cable_from.append(r + 1)  # 1-based row

                # Report cell if it has a block OR has cable connections (shunt with id=0)
                if bid != 0 or cable_from or is_shunt:
                    name = known_blocks.get(bid, f"Block 0x{bid:02X}") if bid != 0 else "shunt"
                    entry = {
                        "block_id": f"0x{bid:02X}" if bid != 0 else "0x00",
                        "name": name,
                    }
                    if is_shunt:
                        entry["shunt"] = True
                    if cable_from:
                        entry["cable_from_rows"] = cable_from
                    block_map[f"r{row+1}c{col+1}"] = entry

        return {
            "success": True,
            "grid": grid,
            "blocks": block_map,
            "rows": 5,
            "cols": 14,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Snapshot / Diff Tools ---

# Internal storage for block snapshots (not persisted across restarts)
_snapshots: dict[str, dict[str, list]] = {}


@mcp.tool()
def fm9_snapshot_block(block_id: str, label: str = "before") -> dict[str, Any]:
    """Take a snapshot of a block's raw data for later diffing.

    Stores the block data internally (not returned to chat). Use fm9_diff_block
    to compare "before" and "after" snapshots.

    Args:
        block_id: Block ID as hex string (e.g., "0x01" for preset meta).
        label: Snapshot label — typically "before" or "after".

    Returns success status with chunk count and sizes.
    """
    try:
        ensure_connected()
        bid_str = block_id if block_id.startswith("0x") else f"0x{int(block_id):02X}"
        bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
        chunks = midi.get_block_data(bid)
        if not chunks:
            return {"success": False, "error": f"No response from block {block_id}."}

        if bid_str not in _snapshots:
            _snapshots[bid_str] = {}
        _snapshots[bid_str][label] = chunks

        return {
            "success": True,
            "block_id": bid_str,
            "label": label,
            "chunk_count": len(chunks),
            "chunk_sizes": [len(c) for c in chunks],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def fm9_diff_block(block_id: str, label_a: str = "before", label_b: str = "after",
                   max_diffs: int = 100) -> dict[str, Any]:
    """Compare two snapshots of a block and return only the differences.

    Args:
        block_id: Block ID as hex string (e.g., "0x01").
        label_a: First snapshot label (default "before").
        label_b: Second snapshot label (default "after").
        max_diffs: Maximum number of byte differences to return (default 100).

    Returns a list of differences: chunk index, byte offset, value in A, value in B.
    """
    try:
        bid_str = block_id if block_id.startswith("0x") else f"0x{int(block_id):02X}"
        if bid_str not in _snapshots:
            return {"success": False, "error": f"No snapshots for block {bid_str}. Use fm9_snapshot_block first."}
        snaps = _snapshots[bid_str]
        if label_a not in snaps:
            return {"success": False, "error": f"Snapshot '{label_a}' not found for {bid_str}. Available: {list(snaps.keys())}"}
        if label_b not in snaps:
            return {"success": False, "error": f"Snapshot '{label_b}' not found for {bid_str}. Available: {list(snaps.keys())}"}

        chunks_a = snaps[label_a]
        chunks_b = snaps[label_b]

        diffs = []
        chunk_count_a = len(chunks_a)
        chunk_count_b = len(chunks_b)
        max_chunks = max(chunk_count_a, chunk_count_b)

        for ci in range(max_chunks):
            if ci >= chunk_count_a:
                diffs.append({"chunk": ci, "type": "added_chunk", "size": len(chunks_b[ci])})
                continue
            if ci >= chunk_count_b:
                diffs.append({"chunk": ci, "type": "removed_chunk", "size": len(chunks_a[ci])})
                continue

            ca = chunks_a[ci]
            cb = chunks_b[ci]
            max_len = max(len(ca), len(cb))

            for bi in range(max_len):
                va = ca[bi] if bi < len(ca) else None
                vb = cb[bi] if bi < len(cb) else None
                if va != vb:
                    diffs.append({
                        "chunk": ci,
                        "offset": bi,
                        "param_idx": (bi - 7) // 3 if bi >= 7 else None,
                        label_a: va,
                        label_b: vb,
                    })
                    if len(diffs) >= max_diffs:
                        break
            if len(diffs) >= max_diffs:
                break

        return {
            "success": True,
            "block_id": bid_str,
            "labels": [label_a, label_b],
            "chunk_counts": [chunk_count_a, chunk_count_b],
            "diff_count": len(diffs),
            "truncated": len(diffs) >= max_diffs,
            "diffs": diffs,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Entry Point ---

if __name__ == "__main__":
    mcp.run(transport="stdio")
