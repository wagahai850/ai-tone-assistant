"""Preset management tools (scene, bypass, channel, store, name, change)."""

from typing import Any

from tools import BLOCKS, DEVICE, midi, ensure_connected, resolve_block_id


def register(mcp):
    """Register preset management tools on the MCP server."""

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

            # Get current preset info
            preset_info = midi.get_preset_info()

            result = {"connected": True, "device": DEVICE.name, "blocks": named_status}
            if preset_info:
                result["preset_number"] = preset_info["preset_number"]
                result["preset_name"] = preset_info["name"]
            return result
        except Exception as e:
            return {"connected": False, "device": DEVICE.name, "error": str(e)}

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
    def fm9_set_scene_name(scene: int, name: str) -> dict[str, Any]:
        """Set the name for a scene in the current preset.

        Args:
            scene: Scene number (1-8).
            name: Scene name (max 32 ASCII characters, e.g. "Clean", "Riff", "Solo").

        Returns success status.
        """
        try:
            ensure_connected()
            if not 1 <= scene <= 8:
                return {"success": False, "error": "Scene must be 1-8."}
            midi.set_scene_name(scene - 1, name)
            return {"success": True, "scene": scene, "name": name}
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
            effect_id = resolve_block_id(block)
            midi.set_bypass(effect_id, bypassed)
            state = "bypassed" if bypassed else "engaged"
            return {"success": True, "block": block, "state": state}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def fm9_set_cab_ir(ir_id: int, block_id: str = "0x3E", slot: int = 1,
                       bank: int = 0) -> dict[str, Any]:
        """Set Cab IR by bank and index.

        Args:
            ir_id: IR index within the bank (0-based).
            block_id: Cab block ID as hex string (default "0x3E" = Cab 1).
            slot: Cab slot (1=R/first, 2=L/second).
            bank: IR bank (0=Factory 1, 1=Factory 2, 2=User, 3=Legacy).

        Returns success status.
        """
        try:
            ensure_connected()
            bid = int(block_id, 16) if block_id.startswith("0x") else int(block_id)
            midi.set_cab_ir(ir_id, bid, slot=slot, bank=bank)
            return {"success": True, "ir_id": ir_id, "bank": bank,
                    "slot": slot, "block_id": block_id}
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

            bid = resolve_block_id(block)
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
