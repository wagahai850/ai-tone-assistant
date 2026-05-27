"""Amp and Drive specific MCP tools with display-value scaling."""

from typing import Any

from tools import (
    AMP_TYPES, DRIVE_TYPES, AMP_PARAMS, DRIVE_PARAMS,
    AMP_NAME_TO_ID, DRIVE_NAME_TO_ID, AMP1_BLOCK_ID, DRIVE1_BLOCK_ID,
    midi, ensure_connected, recalc_checksum,
    decode_param, decode_bipolar, decode_switch,
)


def register(mcp):
    """Register Amp/Drive tools on the MCP server."""

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
        Automatically reads the active channel's parameters (A/B/C/D).
        """
        try:
            ensure_connected()

            # Get current channel from status dump
            status = midi.get_status_dump()
            current_channel = 0
            if AMP1_BLOCK_ID in status:
                current_channel = status[AMP1_BLOCK_ID].get("channel", 0)

            chunks = midi.get_block_data(AMP1_BLOCK_ID)
            if not chunks:
                return {"success": False, "error": "Failed to get Amp 1 block data."}

            # Amp uses separate chunks per channel (multi-chunk block)
            chunk_idx = current_channel if current_channel < len(chunks) else 0
            target_chunk = chunks[chunk_idx]

            params = {}
            for name, info in AMP_PARAMS["params"].items():
                if info["type"] == "enum":
                    continue
                start, end = info["offset"]
                if start + 2 >= len(target_chunk):
                    continue
                lo, hi, msb = target_chunk[start], target_chunk[start + 1], target_chunk[start + 2]

                if info["type"] == "switch":
                    params[name] = decode_switch(lo, hi, msb)
                elif info["type"] == "bipolar":
                    params[name] = decode_bipolar(lo, hi, msb, info["max"])
                else:
                    params[name] = decode_param(lo, hi, msb, info["max"])

            channel_names = {0: "A", 1: "B", 2: "C", 3: "D"}
            return {"success": True, "block": "Amp 1", "channel": channel_names.get(current_channel, "A"), "params": params}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_set_amp_params(params: dict[str, float | bool]) -> dict[str, Any]:
        """Set one or more Amp 1 parameters.

        Args:
            params: A dictionary of parameter name-value pairs. Available parameters:
                - "Gain" (0-10)
                - "Bass" (0-10)
                - "Mid" (0-10)
                - "Treble" (0-10)
                - "Master Volume" (0-10)
                - "Depth" (0-10)
                - "Presence" (0-10)
                - "Level" (-80 to +20 dB)
                - "Balance" (-100 to +100)

        Returns success status, the changes sent, and a full read-back of all
        Amp 1 parameters confirming the actual state on the device.

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

            changes = {}
            for name, value in params.items():
                info = valid_params[name]
                param_id = info["param_id"]
                max_val = info["max"]

                if info["type"] == "switch":
                    midi.set_param_value(AMP1_BLOCK_ID, param_id, 1.0 if value else 0.0, 1.0)
                elif info["type"] == "bipolar":
                    range_val = max_val * 2 if max_val <= 20 else max_val
                    min_val = -max_val if max_val <= 20 else -80
                    normalized = (float(value) - min_val) / (range_val if max_val <= 20 else 100)
                    midi.set_param_value(AMP1_BLOCK_ID, param_id, normalized, 1.0)
                else:
                    midi.set_param_value(AMP1_BLOCK_ID, param_id, float(value), max_val)

                changes[name] = value

            # Read back actual state after SET
            import time
            time.sleep(0.2)
            readback = fm9_get_amp_params()
            if readback.get("success"):
                return {"success": True, "block": "Amp 1", "channel": readback.get("channel", "A"), "changes": changes, "params": readback["params"]}
            return {"success": True, "block": "Amp 1", "changes": changes}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_get_drive_params() -> dict[str, Any]:
        """Get current Drive 1 parameter values.

        Returns all mapped Drive 1 parameters with their current display values.
        Automatically reads the active channel's parameters (A/B/C/D).
        """
        try:
            ensure_connected()

            # Get current channel from status dump
            status = midi.get_status_dump()
            current_channel = 0
            if DRIVE1_BLOCK_ID in status:
                current_channel = status[DRIVE1_BLOCK_ID].get("channel", 0)

            chunks = midi.get_block_data(DRIVE1_BLOCK_ID)
            if not chunks:
                return {"success": False, "error": "Failed to get Drive 1 block data."}

            # Calculate channel offset stride from chunk data
            # Block data contains all 4 channels sequentially after the 7-byte header
            chunk_data_len = len(chunks[0]) - 7  # subtract header
            channel_stride = chunk_data_len // 4
            channel_offset = current_channel * channel_stride

            params = {}
            for name, info in DRIVE_PARAMS["params"].items():
                if info["type"] == "enum":
                    continue
                start = info["offset"][0]
                actual_start = start + channel_offset
                if actual_start + 2 >= len(chunks[0]):
                    continue
                lo, hi, msb = chunks[0][actual_start], chunks[0][actual_start + 1], chunks[0][actual_start + 2]

                if info["type"] == "switch":
                    params[name] = decode_switch(lo, hi, msb)
                elif info["type"] == "bipolar":
                    params[name] = decode_bipolar(lo, hi, msb, info["max"])
                else:
                    params[name] = decode_param(lo, hi, msb, info["max"])

            channel_names = {0: "A", 1: "B", 2: "C", 3: "D"}
            return {"success": True, "block": "Drive 1", "channel": channel_names.get(current_channel, "A"), "params": params}
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

        Returns success status, the changes sent, and a full read-back of all
        Drive 1 parameters confirming the actual state on the device.

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

            changes = {}
            for name, value in params.items():
                info = valid_params[name]
                param_id = info["param_id"]
                max_val = info["max"]

                if info["type"] == "switch":
                    midi.set_param_value(DRIVE1_BLOCK_ID, param_id, 1.0 if value else 0.0, 1.0)
                elif info["type"] == "bipolar":
                    normalized = (float(value) + max_val / 2) / max_val
                    midi.set_param_value(DRIVE1_BLOCK_ID, param_id, normalized, 1.0)
                else:
                    midi.set_param_value(DRIVE1_BLOCK_ID, param_id, float(value), max_val)

                changes[name] = value

            # Read back actual state after SET
            import time
            time.sleep(0.2)
            readback = fm9_get_drive_params()
            if readback.get("success"):
                return {"success": True, "block": "Drive 1", "channel": readback.get("channel", "A"), "changes": changes, "params": readback["params"]}
            return {"success": True, "block": "Drive 1", "changes": changes}
        except Exception as e:
            return {"success": False, "error": str(e)}
