"""Generic block parameter tools (normalized 0-1 values)."""

from typing import Any

from tools import (
    ALL_PARAMS, EFFECT_DEFS, TYPE_VALID_PARAMS,
    midi, ensure_connected, resolve_block, resolve_param,
)

# --- Enum Name Resolution Tables ---

# Cab Mode: pid 31
CAB_MODE_NAMES = {
    0: "Mono Hi-Res",
    1: "DynaCab",
    2: "Stereo Hi-Res",
    3: "Ultra-Res",
    4: "Ultra-Res Stereo",
}

# DynaCab Mic: pid 89-92
DYNACAB_MIC_NAMES = {
    0: "Condenser",
    1: "Ribbon",
    2: "Dynamic 1",
    3: "Dynamic 2",
}

# Cab block enum resolution: param_id -> (lookup_key_in_EFFECT_DEFS or dict)
CAB_ENUM_RESOLVERS = {
    31: CAB_MODE_NAMES,          # Mode
    85: "dynacab_types",         # DynaCab Type1 (dedicated list, raw=0-indexed)
    86: "dynacab_types",         # DynaCab Type2
    87: "dynacab_types",         # DynaCab Type3
    88: "dynacab_types",         # DynaCab Type4
    89: DYNACAB_MIC_NAMES,       # DynaCab Mic1
    90: DYNACAB_MIC_NAMES,       # DynaCab Mic2
    91: DYNACAB_MIC_NAMES,       # DynaCab Mic3
    92: DYNACAB_MIC_NAMES,       # DynaCab Mic4
}

CAB_BLOCK_IDS_SET = {0x3E, 0x3F, 0x40, 0x41}  # Cab 1-4


def _resolve_enum_name(block_id: int, pid: int, raw_val: int) -> str | None:
    """Resolve an enum raw value to a human-readable name, if possible."""
    if block_id in CAB_BLOCK_IDS_SET and pid in CAB_ENUM_RESOLVERS:
        resolver = CAB_ENUM_RESOLVERS[pid]
        if isinstance(resolver, dict):
            return resolver.get(raw_val)
        elif isinstance(resolver, str):
            # Lookup in EFFECT_DEFS list (raw value is direct 0-indexed)
            names = EFFECT_DEFS.get(resolver, [])
            if 0 <= raw_val < len(names):
                return names[raw_val]
    return None


def _resolve_cab_enum_value(pid: int, value) -> int:
    """Resolve a cab enum value from either integer index or string name.

    For DynaCab Type (pid 85-88): accepts int index or cab name string.
    For DynaCab Mic (pid 89-92): accepts int index or mic name string.
    For Mode (pid 31): accepts int index or mode name string.
    """
    # If it's already a number, return as int
    if isinstance(value, (int, float)) and not isinstance(value, str):
        return int(value)

    # String-based lookup
    value_str = str(value).strip()

    # Try integer string first
    try:
        return int(value_str)
    except ValueError:
        pass

    # DynaCab Type (pid 85-88): lookup in dynacab_types list
    if pid in (85, 86, 87, 88):
        names = EFFECT_DEFS.get("dynacab_types", [])
        # Exact match (case-insensitive)
        for i, name in enumerate(names):
            if name.lower() == value_str.lower():
                return i
        # Partial match
        matches = [(i, name) for i, name in enumerate(names)
                   if value_str.lower() in name.lower()]
        if len(matches) == 1:
            return matches[0][0]
        elif len(matches) > 1:
            raise ValueError(
                f"Ambiguous DynaCab Type '{value_str}'. Matches: {[m[1] for m in matches[:10]]}"
            )
        raise ValueError(f"DynaCab Type '{value_str}' not found. Use fm9_list_effect_types('cab') or integer index.")

    # DynaCab Mic (pid 89-92): lookup in DYNACAB_MIC_NAMES
    if pid in (89, 90, 91, 92):
        for idx, name in DYNACAB_MIC_NAMES.items():
            if name.lower() == value_str.lower():
                return idx
        raise ValueError(f"DynaCab Mic '{value_str}' not found. Valid: {list(DYNACAB_MIC_NAMES.values())}")

    # Mode (pid 31): lookup in CAB_MODE_NAMES
    if pid == 31:
        for idx, name in CAB_MODE_NAMES.items():
            if name.lower() == value_str.lower():
                return idx
        raise ValueError(f"Cab Mode '{value_str}' not found. Valid: {list(CAB_MODE_NAMES.values())}")

    # Fallback: try int conversion
    return int(value)


def register(mcp):
    """Register generic block tools on the MCP server."""

    @mcp.tool()
    def fm9_set_effect_type(block: str, type_name: str) -> dict[str, Any]:
        """Set the effect type/model for any block by name.

        Args:
            block: Block name (e.g., "Delay 1", "Reverb 1", "Chorus 1") or hex ID.
            type_name: Type/model name. Use fm9_list_effect_types to find available names.

        Works for all blocks that have selectable types (Delay, Reverb, Chorus,
        Flanger, Phaser, Pitch, Compressor, etc.). For Amp and Drive, prefer
        the dedicated fm9_set_amp_type / fm9_set_drive_type tools.

        Returns success status and the type that was set.
        """
        try:
            ensure_connected()
            prefix, block_info = resolve_block(block)
            block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
            if not block_id:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            # Find the type_id by matching type_name in EFFECT_DEFS
            # Determine which effect_defs key to search
            block_lower = block_info["block_name"].lower()
            # Strip instance number for lookup
            import re
            base_name = re.sub(r'\s*\d+$', '', block_lower).strip()

            key_map = {
                "amp": "amp_models",
                "drive": "drive_models",
                "delay": "delay_types",
                "reverb": "reverb_types",
                "chorus": "chorus_types",
                "flanger": "flanger_types",
                "phaser": "phaser_types",
                "pitch": "pitch_types",
                "tremolo/panner": "tremolo_types",
                "tremolo": "tremolo_types",
                "wah": "wah_types",
                "compressor": "compressor_types",
                "graphic eq": "geq_types",
                "filter": "filter_types",
                "synth": "synth_types",
                "multitap delay": "multitap_delay_types",
                "plex delay": "plex_delay_types",
            }

            defs_key = key_map.get(base_name)
            if not defs_key or defs_key not in EFFECT_DEFS:
                if base_name == "cab":
                    return {
                        "success": False,
                        "error": (
                            f"Cab block does not support fm9_set_effect_type. "
                            f"Use fm9_set_block_params(block=\"{block}\", params={{\"Dynacab Type1\": \"<name>\"}}) "
                            f"for DynaCab Type, or fm9_set_cab_ir() for IR mode. "
                            f"Available DynaCab types: use integer index 0-44 or name (e.g. '4x12 1960TV')."
                        ),
                    }
                return {"success": False, "error": f"No type list found for block '{block}' (base: '{base_name}')."}

            type_list = EFFECT_DEFS[defs_key]

            # Find type_id (index in the list)
            type_id = None
            matched_name = None

            # Exact match first
            for i, name in enumerate(type_list):
                if name.lower() == type_name.lower():
                    type_id = i
                    matched_name = name
                    break

            # Partial match
            if type_id is None:
                matches = [(i, name) for i, name in enumerate(type_list)
                           if type_name.lower() in name.lower()]
                if len(matches) == 1:
                    type_id, matched_name = matches[0]
                elif len(matches) > 1:
                    return {
                        "success": False,
                        "error": f"Ambiguous type '{type_name}'. Matches: {[m[1] for m in matches[:10]]}",
                    }
                else:
                    return {"success": False, "error": f"Type '{type_name}' not found for {block_info['block_name']}."}

            # Find the actual Type param_id for this block
            # Known Type param_ids from PROTOCOL.md (per block category)
            TYPE_PID_MAP = {
                "amp": 10, "drive": 0, "delay": 11, "reverb": 10,
                "chorus": 0, "flanger": 0, "phaser": 0, "pitch": 0,
                "wah": 0, "tremolo/panner": 0, "tremolo": 0,
                "compressor": 12, "graphic eq": 15, "enhancer": 6,
                "volume/pan": 9, "megatap delay": 28, "ring modulator": 10,
                "ten-tap delay": 0, "filter": 0, "synth": 0,
                "plex delay": 0, "multitap delay": 0,
            }
            type_pid = TYPE_PID_MAP.get(base_name)
            if type_pid is None:
                return {"success": False, "error": f"No Type param_id known for block '{base_name}'. Add it to TYPE_PID_MAP."}

            # Send type change as raw_float (same encoding as PEQ/Cab enum params)
            midi.set_param_value(block_id, type_pid, float(type_id), 1.0, raw_float=True)
            return {"success": True, "block": block_info["block_name"], "type": matched_name, "type_id": type_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _decode_block_params(block_id: int, block_info: dict, chunks: list, channel: int = 0) -> dict:
        """Decode all parameters from block data chunks into display values.

        Args:
            block_id: Block ID
            block_info: Block metadata from ALL_PARAMS
            chunks: Raw chunk data from get_block_data
            channel: Channel index (0=A, 1=B, 2=C, 3=D)

        Decode algorithm dispatch (6 patterns, confirmed 2026-06-04):
          Pattern 1: decode_scale=="4096" → (raw+4)/4096 * display_max
          Pattern 2: decode_style=="center" → (raw-32767)/32767 * decode_max
          Pattern 3: type=="bipolar" + decode_style=="zero" → raw/65534 * decode_max + min
          Pattern 4: continuous (default) → raw/65534 * decode_max
          Pattern 5: type=="frequency" + max>=2000 → min * 10^(raw/65534 * log10(dm/min))
          Pattern 6: type=="signed_int" → two's complement

        Channel data layout: all chunks are concatenated (stripping 7-byte SysEx
        headers from chunks after the first), then channels are accessed via
        stride = (combined_len - 7) // 4.
        """
        import math

        # Concatenate all chunks (strip 7-byte header + last byte checksum)
        combined = list(chunks[0][:-1])
        for c in chunks[1:]:
            combined.extend(c[7:-1])

        # Calculate channel stride from combined data
        channel_stride = (len(combined) - 7) // 4
        channel_offset = channel * channel_stride

        params = {}
        for pid_str, pinfo in block_info["params"].items():
            pid = int(pid_str)
            offset = 7 + pid * 3 + channel_offset
            if offset + 2 >= len(combined):
                continue
            lo = combined[offset]
            hi = combined[offset + 1]
            msb = combined[offset + 2]
            raw_val = lo | (hi << 7) | (msb << 14)

            param_type = pinfo.get("type", "continuous")
            param_max = pinfo.get("max", 10.0)
            param_min = pinfo.get("min", 0)
            decode_max = pinfo.get("decode_max", None)
            decode_style = pinfo.get("decode_style", None)
            decode_scale = pinfo.get("decode_scale", None)

            # --- Dispatch decode algorithm ---

            if param_type == "switch":
                display_value = bool(lo)

            elif param_type == "enum":
                display_value = raw_val

            elif param_type == "signed_int":
                # Pattern 6: Two's complement
                display_value = raw_val if raw_val <= 32767 else raw_val - 65536

            elif decode_scale == "4096":
                # Pattern 1: 4096-scale fixed point (flags=0x0430, 4 params only)
                # raw range 0-4092, decode = (raw+4)/4096 * display_max
                if raw_val == 0:
                    display_value = 0.0
                else:
                    display_value = round((raw_val + 4) / 4096.0 * param_max, 2)

            elif decode_style == "center":
                # Pattern 2: Center bipolar (raw=32767 is zero)
                effective_max = decode_max if decode_max else param_max
                display_value = round((raw_val - 32767) / 32767.0 * effective_max, 2)

            elif param_type == "bipolar" and decode_style == "zero":
                # Pattern 3: Zero-based bipolar (raw=0→min, raw=65534→max)
                effective_max = decode_max if decode_max else (param_max - param_min)
                display_value = round(raw_val / 65534.0 * effective_max + param_min, 2)

            elif param_type == "frequency" and param_max >= 2000:
                # Pattern 5: Frequency log scale
                min_freq = max(param_min, 20.0)
                effective_max = decode_max if decode_max else param_max
                if raw_val == 0:
                    display_value = min_freq
                else:
                    display_value = round(
                        min_freq * 10 ** (raw_val / 65534.0 * math.log10(effective_max / min_freq)), 1
                    )

            elif param_type == "bipolar":
                # Uncalibrated bipolar fallback: assume linear full-range
                # raw/65534 * (max-min) + min
                effective_range = (param_max - param_min) if param_max != param_min else param_max * 2
                display_value = round(raw_val / 65534.0 * effective_range + param_min, 2)

            else:
                # Pattern 4: Continuous / linear frequency (default)
                # raw=0→0, raw=65534→decode_max (or display_max if uncalibrated)
                effective_max = decode_max if decode_max else param_max
                display_value = round(raw_val / 65534.0 * effective_max, 2)

            # --- Build result entry ---

            entry = {
                "value": display_value,
                "raw": raw_val,
                "param_id": pid,
                "type": param_type,
            }
            if param_type not in ("switch", "enum"):
                entry["min"] = param_min
                entry["max"] = param_max

            # Resolve enum names where possible
            if param_type == "enum":
                enum_name = _resolve_enum_name(block_id, pid, raw_val)
                if enum_name:
                    entry["name"] = enum_name

            params[pinfo["display_name"]] = entry

        return params

    @mcp.tool()
    def fm9_get_block_params(block: str, channel: str | None = None) -> dict[str, Any]:
        """Get current parameter values for any effect block.

        Args:
            block: Block name (e.g., "Amp 1", "Delay 1", "Chorus") or hex ID (e.g., "0x3A").
            channel: Optional channel to read ("A", "B", "C", "D"). If omitted, reads
                     the currently active channel for this block.

        Returns all mapped parameters with their current display values.
        """
        try:
            ensure_connected()
            prefix, block_info = resolve_block(block)
            block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
            if not block_id:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            # Determine channel index
            channel_map = {"A": 0, "B": 1, "C": 2, "D": 3}
            if channel:
                target_channel = channel_map.get(channel.upper())
                if target_channel is None:
                    return {"success": False, "error": f"Invalid channel '{channel}'. Use A/B/C/D."}
            else:
                # Read active channel from status dump
                status = midi.get_status_dump()
                target_channel = 0
                if block_id in status:
                    target_channel = status[block_id].get("channel", 0)

            chunks = midi.get_block_data(block_id)
            if not chunks:
                return {"success": False, "error": f"Failed to get block data for {block_info['block_name']}."}

            params = _decode_block_params(block_id, block_info, chunks, channel=target_channel)

            channel_names = {0: "A", 1: "B", 2: "C", 3: "D"}
            return {
                "success": True,
                "block": block_info["block_name"],
                "block_id": f"0x{block_id:02X}",
                "channel": channel_names.get(target_channel, "A"),
                "param_count": len(params),
                "params": params,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_set_block_params(block: str, params: dict[str, float | int | str],
                             channel: str | None = None, scene: int | None = None) -> dict[str, Any]:
        """Set one or more parameters on any effect block.

        Args:
            block: Block name (e.g., "Amp 1", "Delay 1", "Chorus") or hex ID (e.g., "0x3A").
            params: Dictionary of parameter name-value pairs.
                    Values are display values sent directly to the device:
                    - Continuous params: display value (e.g., Mix=50 for 50%)
                    - Frequency params: Hz value (e.g., 2500 for 2500 Hz)
                    - Enum/Type params: integer index (e.g., 0=first type)
                    - Switch params: 0 or 1
                    For Amp/Drive, use the dedicated fm9_set_amp_params/fm9_set_drive_params
                    tools instead (they handle the different normalized encoding).
                    For Cab DynaCab Type: use integer index (0-44) or name (e.g. "4x12 1960TV").
                    For Cab DynaCab Mic: use integer (0-3) or name (e.g. "Dynamic 1").
                    For Cab DynaCab R1-R4, Z1-Z4: use normalized 0.0-1.0 (e.g. 0.5 = center).
                    For Pitch Shift1-4 (Virtual Capo): use semitone value directly (e.g. -1 for down 1 semitone).
            channel: Optional target channel ("A", "B", "C", "D"). If omitted, writes to
                     the currently active channel. The server switches internally and restores.
            scene: Optional target scene (1-8). If omitted, uses the current scene.
                   The server switches internally and restores after writing.

        Returns success status, the changes sent, and a full read-back of all
        block parameters confirming the actual state on the device. No separate
        GET call is needed after SET.

        Example: fm9_set_block_params(block="Chorus 1", params={"Rate": 0.5, "Depth": 0.7})
        Example: fm9_set_block_params(block="Amp 1", params={"Gain": 8.0}, channel="B", scene=2)
        """
        try:
            ensure_connected()
            prefix, block_info = resolve_block(block)
            block_id = block_info.get("_block_id_int") or block_info.get("block_id_base")
            if not block_id:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            # --- Scene/Channel state management ---
            channel_map = {"A": 0, "B": 1, "C": 2, "D": 3}
            original_scene = None
            original_channel = None

            # Get current state
            status = midi.get_status_dump()
            current_channel = 0
            if block_id in status:
                current_channel = status[block_id].get("channel", 0)

            # Switch scene if requested
            if scene is not None:
                scene_idx = scene - 1  # API is 1-based, protocol is 0-based
                if not (0 <= scene_idx <= 7):
                    return {"success": False, "error": f"Invalid scene {scene}. Use 1-8."}
                original_scene = midi.get_status_dump().get("_scene", None)
                midi.set_scene(scene_idx)
                import time
                time.sleep(0.2)
                # Re-read status after scene change (channel may have changed)
                status = midi.get_status_dump()
                if block_id in status:
                    current_channel = status[block_id].get("channel", 0)

            # Switch channel if requested
            target_channel = current_channel
            if channel:
                target_channel = channel_map.get(channel.upper())
                if target_channel is None:
                    return {"success": False, "error": f"Invalid channel '{channel}'. Use A/B/C/D."}
                if target_channel != current_channel:
                    original_channel = current_channel
                    midi.set_channel(block_id, target_channel)
                    import time
                    time.sleep(0.1)

            # Cab blocks have mixed encoding:
            # - Frequency params (Hz), Mode, Mute: raw float via set_param_value
            # - DynaCab Type/Mic: enum via _send_sub09 (integer index)
            # - DynaCab R/Z (position/distance): normalized 0-1
            # - Other continuous params: needs verification (assume raw float)
            CAB_BLOCK_IDS = {0x3E, 0x3F, 0x40, 0x41}  # Cab 1-4

            # Params that use NORMALIZED 0-1 encoding (like Amp/Drive)
            CAB_NORMALIZED_PARAMS = {
                93, 94, 95, 96,   # Dynacab R1-R4 (position)
                97, 98, 99, 104,  # Dynacab Z1-Z4 (distance)
            }

            # Enum params that must be sent as raw float (integer value as IEEE 754)
            # Verified via Wireshark: Editor sends sub=0x09 SET_PARAM with raw float
            # e.g., Mode=1.0, DynaCab Type1=42.0, DynaCab Mic1=2.0
            CAB_ENUM_PARAMS = {
                31,               # Mode
                85, 86, 87, 88,   # Dynacab Type1-4
                89, 90, 91, 92,   # Dynacab Mic1-4
            }

            # Param_id overrides (generic name -> correct per-mic pid)
            CAB_PID_OVERRIDES = {
                "highcut": 66,
                "lowcut": 62,
            }

            changes = {}

            for param_name, value in params.items():
                pid, internal_name = resolve_param(block_info, param_name)

                if block_id in CAB_BLOCK_IDS:
                    # Check for pid override
                    normalized_name = param_name.lower().replace(" ", "").replace("_", "")
                    if normalized_name in CAB_PID_OVERRIDES:
                        pid = CAB_PID_OVERRIDES[normalized_name]

                    if pid in CAB_ENUM_PARAMS:
                        # Enum params: send integer as raw float (verified via Wireshark)
                        int_value = _resolve_cab_enum_value(pid, value)
                        midi.set_param_value(block_id, pid, float(int_value), 1.0,
                                             raw_float=True)
                    elif pid in CAB_NORMALIZED_PARAMS:
                        # These use standard normalized 0-1
                        midi.set_param_value(block_id, pid, float(value), 1.0)
                    else:
                        # Everything else on Cab uses raw float
                        midi.set_param_value(block_id, pid, float(value), 1.0,
                                             raw_float=True)
                else:
                    # Amp and Drive blocks use normalized 0-1 encoding
                    # (same as fm9_set_amp_params / fm9_set_drive_params)
                    AMP_DRIVE_BLOCK_IDS = {0x3A, 0x3B, 0x3C, 0x3D,  # Amp 1-4
                                           0x76, 0x77, 0x78, 0x79}  # Drive 1-4
                    if block_id in AMP_DRIVE_BLOCK_IDS:
                        # Look up param metadata for encoding
                        pid_str = str(pid)
                        pinfo = block_info["params"].get(pid_str, {})
                        param_type = pinfo.get("type", "continuous")
                        param_max = pinfo.get("max", 10.0)

                        if param_type == "switch":
                            midi.set_param_value(block_id, pid, 1.0 if value else 0.0, 1.0)
                        elif param_type == "bipolar":
                            # Bipolar params use raw_float (display value sent directly)
                            midi.set_param_value(block_id, pid, float(value), 1.0, raw_float=True)
                        else:
                            midi.set_param_value(block_id, pid, float(value), param_max)
                    else:
                        # Effect blocks: ALL params use normalized encoding.
                        # SET sends IEEE 754 float normalized to 0.0-1.0 range.
                        # FM9 interprets: continuous → value * display_max
                        #                 bipolar → value * (max-min) + min
                        pid_str = str(pid)
                        pinfo = block_info["params"].get(pid_str, {})
                        param_type = pinfo.get("type", "continuous")
                        param_max = pinfo.get("max", 10.0)
                        param_min = pinfo.get("min", 0)

                        if param_type == "switch":
                            midi.set_param_value(block_id, pid, 1.0 if value else 0.0, 1.0,
                                                 raw_float=True)
                        elif param_type == "signed_int":
                            # Signed integer (e.g., Pitch Shift): raw float
                            midi.set_param_value(block_id, pid, float(value), 1.0,
                                                 raw_float=True)
                        elif param_type == "enum":
                            # Enum: send integer as raw float
                            midi.set_param_value(block_id, pid, float(value), 1.0,
                                                 raw_float=True)
                        elif param_type == "frequency":
                            # Frequency (Hz): raw float (FM9 expects Hz directly)
                            midi.set_param_value(block_id, pid, float(value), 1.0,
                                                 raw_float=True)
                        elif param_type == "bipolar":
                            # Bipolar: normalized = value / max
                            # FM9 interprets: 0.0=center, +1.0=max, -1.0=min
                            # e.g., Feed=20% (max=100) → 20/100=0.2 → FM9 shows +20%
                            midi.set_param_value(block_id, pid, float(value), param_max)
                        else:
                            # Continuous: normalized = value / max
                            midi.set_param_value(block_id, pid, float(value), param_max)

                changes[param_name] = value

            # Read back actual state after SET (confirms FM9 accepted values)
            import time
            time.sleep(0.2)  # Allow FM9 to process

            chunks = midi.get_block_data(block_id)

            # --- Restore original scene/channel ---
            if original_channel is not None:
                midi.set_channel(block_id, original_channel)
                time.sleep(0.1)
            if original_scene is not None:
                midi.set_scene(original_scene)
                time.sleep(0.1)

            channel_names = {0: "A", 1: "B", 2: "C", 3: "D"}
            if chunks:
                actual_params = _decode_block_params(block_id, block_info, chunks, channel=target_channel)
                return {
                    "success": True,
                    "block": block_info["block_name"],
                    "block_id": f"0x{block_id:02X}",
                    "channel": channel_names.get(target_channel, "A"),
                    "changes": changes,
                    "params": actual_params,
                }
            else:
                return {
                    "success": True,
                    "block": block_info["block_name"],
                    "block_id": f"0x{block_id:02X}",
                    "channel": channel_names.get(target_channel, "A"),
                    "changes": changes,
                    "note": "Read-back failed; values were sent but could not be verified.",
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_list_block_params(block: str) -> dict[str, Any]:
        """List all known parameters for a block.

        Args:
            block: Block name (e.g., "Amp 1", "Delay 1", "Chorus") or hex ID.

        Returns parameter names and IDs for the specified block.
        """
        try:
            prefix, block_info = resolve_block(block)
            params_list = []
            for pid_str, pinfo in sorted(block_info["params"].items(), key=lambda x: int(x[0])):
                entry = {
                    "param_id": int(pid_str),
                    "display_name": pinfo["display_name"],
                    "internal_name": pinfo["name"],
                }
                # Schema v2: type/min/max are direct fields (no "meta" wrapper)
                if "type" in pinfo:
                    entry["type"] = pinfo["type"]
                    entry["min"] = pinfo.get("min", 0)
                    entry["max"] = pinfo.get("max", 10.0)
                    entry["verified"] = pinfo.get("verified", False)
                params_list.append(entry)

            block_id_int = block_info.get("_block_id_int", block_info.get("block_id_base"))
            return {
                "success": True,
                "block": block_info["block_name"],
                "block_id": f"0x{block_id_int:02X}" if block_id_int else None,
                "param_count": len(params_list),
                "params": params_list,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_list_effect_types(block: str) -> dict[str, Any]:
        """List available effect types/models for a block.

        Args:
            block: Block category name. Valid values:
                   "amp", "drive", "delay", "reverb", "chorus", "flanger",
                   "phaser", "pitch", "tremolo", "wah", "compressor", "geq",
                   "filter", "cab", "multitap", "plex", "synth"

        Returns list of type/model names available for that block.
        """
        try:
            block_lower = block.lower().strip()
            key_map = {
                "amp": "amp_models",
                "drive": "drive_models",
                "delay": "delay_types",
                "reverb": "reverb_types",
                "chorus": "chorus_types" if "chorus_types" in EFFECT_DEFS else None,
                "flanger": "flanger_types",
                "phaser": "phaser_types",
                "pitch": "pitch_types",
                "tremolo": "tremolo_types",
                "wah": "wah_types",
                "compressor": "compressor_types",
                "geq": "geq_types",
                "filter": "filter_types",
                "cab": "cab_factory_1",
                "cab_legacy": "cab_legacy",
                "multitap": "multitap_delay_types",
                "plex": "plex_delay_types",
                "synth": "synth_types",
            }

            key = key_map.get(block_lower)
            if not key or key not in EFFECT_DEFS:
                available = sorted(key_map.keys())
                return {"success": False, "error": f"Unknown block '{block}'. Available: {available}"}

            names = EFFECT_DEFS[key]
            return {
                "success": True,
                "block": block,
                "type_count": len(names),
                "types": names,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
