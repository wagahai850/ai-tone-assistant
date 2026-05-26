"""Generic block parameter tools (normalized 0-1 values)."""

from typing import Any

from tools import (
    ALL_PARAMS, EFFECT_DEFS, TYPE_VALID_PARAMS,
    midi, ensure_connected, resolve_block, resolve_param,
)


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
            block_id_str = block_info.get("block_id")
            if not block_id_str:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            block_id = int(block_id_str, 16)

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

            # Send sub=0x09, param=0x0A (TYPE parameter) with type_id
            midi._send_sub09(block_id, 0x0A, type_id)
            return {"success": True, "block": block_info["block_name"], "type": matched_name, "type_id": type_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_get_block_params(block: str) -> dict[str, Any]:
        """Get current parameter values for any effect block.

        Args:
            block: Block name (e.g., "Amp 1", "Delay 1", "Chorus") or hex ID (e.g., "0x3A").

        Returns all mapped parameters with their current display values.
        """
        try:
            ensure_connected()
            prefix, block_info = resolve_block(block)
            block_id_str = block_info.get("block_id")
            if not block_id_str:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            block_id = int(block_id_str, 16)
            chunks = midi.get_block_data(block_id)
            if not chunks:
                return {"success": False, "error": f"Failed to get block data for {block_info['block_name']}."}

            params = {}
            for pid_str, pinfo in block_info["params"].items():
                pid = int(pid_str)
                offset = 7 + pid * 3
                if offset + 2 >= len(chunks[0]):
                    continue
                lo = chunks[0][offset]
                hi = chunks[0][offset + 1]
                msb = chunks[0][offset + 2]
                raw_val = lo | (hi << 7) | (msb << 14)

                meta = pinfo.get("meta", {})
                param_type = meta.get("type", "continuous")
                param_max = meta.get("max", 10.0)
                param_min = meta.get("min", 0)

                # Calculate display value based on type
                if param_type == "switch":
                    display_value = bool(lo)
                elif param_type == "enum":
                    display_value = raw_val
                elif param_type == "bipolar":
                    # Bipolar: raw 0 = -max, 32767 = 0 (center), 65534 = +max
                    # Uses same formula as decode_bipolar: raw/65534 * (2*max) - max
                    display_value = round(raw_val / 65534.0 * (2 * param_max) - param_max, 2)
                else:
                    # Continuous: raw 0 = 0, 65534 = max
                    normalized = raw_val / 65534.0 if raw_val <= 65534 else raw_val
                    display_value = round(normalized * param_max, 2)

                entry = {
                    "value": display_value,
                    "raw": raw_val,
                    "param_id": pid,
                    "type": param_type,
                }
                if param_type not in ("switch", "enum"):
                    entry["min"] = param_min
                    entry["max"] = param_max

                params[pinfo["display_name"]] = entry

            return {
                "success": True,
                "block": block_info["block_name"],
                "block_id": block_id_str,
                "param_count": len(params),
                "params": params,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_set_block_params(block: str, params: dict[str, float]) -> dict[str, Any]:
        """Set one or more parameters on any effect block.

        Args:
            block: Block name (e.g., "Amp 1", "Delay 1", "Chorus") or hex ID (e.g., "0x3A").
            params: Dictionary of parameter name-value pairs.
                    Values are normalized 0.0-1.0 (will be sent as IEEE 754 float).
                    For known blocks (Amp, Drive), use the dedicated tools instead for
                    proper display-value scaling.

        Example: fm9_set_block_params(block="Chorus 1", params={"Rate": 0.5, "Depth": 0.7})
        """
        try:
            ensure_connected()
            prefix, block_info = resolve_block(block)
            block_id_str = block_info.get("block_id")
            if not block_id_str:
                return {"success": False, "error": f"Block '{block}' has no known block_id."}

            block_id = int(block_id_str, 16)
            changes = {}

            for param_name, value in params.items():
                pid, internal_name = resolve_param(block_info, param_name)
                # Value is normalized 0.0-1.0, send directly
                midi.set_param_value(block_id, pid, float(value), 1.0)
                changes[param_name] = value

            return {
                "success": True,
                "block": block_info["block_name"],
                "block_id": block_id_str,
                "changes": changes,
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
                meta = pinfo.get("meta")
                if meta:
                    entry["type"] = meta.get("type", "unknown")
                    entry["min"] = meta.get("min", 0)
                    entry["max"] = meta.get("max", 10.0)
                    entry["verified"] = meta.get("verified", False)
                params_list.append(entry)

            return {
                "success": True,
                "block": block_info["block_name"],
                "block_id": block_info.get("block_id"),
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
