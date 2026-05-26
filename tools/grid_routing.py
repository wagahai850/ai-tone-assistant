"""Grid layout and routing tools (add/delete/move/connect blocks)."""

from typing import Any

from tools import BLOCKS, midi, ensure_connected


# Known block types for add_block (user-friendly names)
BLOCK_TYPE_MAP = {
    "Input 1": 0x25, "Input1": 0x25,
    "Output 1": 0x2A, "Output1": 0x2A,
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
    "Compressor 1": 0x2E, "Comp1": 0x2E, "Comp 1": 0x2E,
    "Compressor 2": 0x2F, "Comp2": 0x2F, "Comp 2": 0x2F,
    "Graphic EQ 1": 0x32, "GEQ": 0x32, "GEQ 1": 0x32,
    "Graphic EQ 2": 0x33, "GEQ 2": 0x33,
    "Parametric EQ 1": 0x36, "PEQ": 0x36, "PEQ 1": 0x36,
    "Parametric EQ 2": 0x37, "PEQ 2": 0x37,
    "Gate 1": 0x92, "Gate1": 0x92, "Gate/Expander 1": 0x92,
    "Gate 2": 0x93, "Gate2": 0x93, "Gate/Expander 2": 0x93,
    "Flanger 1": 0x52, "Flanger1": 0x52,
    "Flanger 2": 0x53, "Flanger2": 0x53,
    "Phaser 1": 0x5A, "Phaser1": 0x5A,
    "Phaser 2": 0x5B, "Phaser2": 0x5B,
    "Wah 1": 0x5E, "Wah1": 0x5E,
    "Wah 2": 0x5F, "Wah2": 0x5F,
    "Pitch 1": 0x6E, "Pitch1": 0x6E,
    "Pitch 2": 0x6F, "Pitch2": 0x6F,
    "Multitap Delay 1": 0x4A, "Multitap1": 0x4A, "Multitap 1": 0x4A,
    "Multitap Delay 2": 0x4B, "Multitap2": 0x4B, "Multitap 2": 0x4B,
    "Enhancer 1": 0x7A, "Enhancer": 0x7A,
    "Enhancer 2": 0x7B,
    "Tremolo 1": 0x6A, "Tremolo1": 0x6A, "Tremolo/Panner 1": 0x6A,
    "Tremolo 2": 0x6B, "Tremolo2": 0x6B, "Tremolo/Panner 2": 0x6B,
    "Rotary 1": 0x56, "Rotary1": 0x56,
    "Rotary 2": 0x57, "Rotary2": 0x57,
    "Filter 1": 0x72, "Filter1": 0x72,
    "Filter 2": 0x73, "Filter2": 0x73,
    "Formant 1": 0x62, "Formant1": 0x62,
    "Formant 2": 0x63, "Formant2": 0x63,
    "Volume/Pan 1": 0x66, "Vol/Pan 1": 0x66,
    "Volume/Pan 2": 0x67, "Vol/Pan 2": 0x67,
    "Synth 1": 0x82, "Synth1": 0x82,
    "Synth 2": 0x83, "Synth2": 0x83,
    "Megatap Delay 1": 0x8A, "Megatap 1": 0x8A,
    "Megatap Delay 2": 0x8B, "Megatap 2": 0x8B,
    "Plex Delay 1": 0xB2, "Plex 1": 0xB2,
    "Plex Delay 2": 0xB3, "Plex 2": 0xB3,
    "Ring Modulator": 0x96, "Ring Mod": 0x96,
    "Looper": 0xA6,
}


def register(mcp):
    """Register grid/routing tools on the MCP server."""

    @mcp.tool()
    def fm9_add_block(block_type: str, row: int, col: int) -> dict[str, Any]:
        """Add an effect block to the FM9 grid at a specific position.

        If the position already contains a block or shunt, it will be replaced.
        No need to delete first — this works as an upsert.

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
            if block_type.startswith("0x"):
                bid = int(block_type, 16)
            elif block_type in BLOCK_TYPE_MAP:
                bid = BLOCK_TYPE_MAP[block_type]
            else:
                for name, block_id in BLOCK_TYPE_MAP.items():
                    if name.lower() == block_type.lower():
                        bid = block_id
                        break
                else:
                    return {
                        "success": False,
                        "error": f"Unknown block type '{block_type}'. Known: {sorted(set(BLOCK_TYPE_MAP.keys()))}",
                    }

            if not (1 <= row <= 5):
                return {"success": False, "error": "Row must be 1-5."}
            if not (1 <= col <= 14):
                return {"success": False, "error": "Column must be 1-14."}

            midi.add_block_at(bid, row - 1, col - 1)

            # Verify block was actually added
            import time
            time.sleep(0.3)
            status = midi.get_status_dump()
            if bid not in status:
                return {
                    "success": False,
                    "error": f"Block 0x{bid:02X} was not added. The device did not acknowledge the operation. "
                             f"Verify the block type is valid and the grid position is empty.",
                    "block_type": block_type,
                    "block_id": f"0x{bid:02X}",
                    "position": {"row": row, "col": col},
                }

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

        from_col must be less than to_col (cables go left to right).
        Blocks can be on different rows.
        Intermediate columns will have shunt (pass-through) blocks placed automatically.

        Args:
            from_row: Row of the source block (1-5).
            from_col: Column of the source block (1-14).
            to_row: Row of the destination block (1-5).
            to_col: Column of the destination block (must be > from_col).

        Returns success status.
        """
        try:
            ensure_connected()
            if not (1 <= from_row <= 5) or not (1 <= to_row <= 5):
                return {"success": False, "error": "Row must be 1-5."}
            if not (1 <= from_col <= 14) or not (1 <= to_col <= 14):
                return {"success": False, "error": "Column must be 1-14."}
            if from_col >= to_col and from_row == to_row:
                return {"success": False, "error": "from_col must be less than to_col for same-row connections."}
            if from_col > to_col and from_row != to_row:
                return {"success": False, "error": "from_col must be <= to_col for cross-row connections."}

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
    @mcp.tool()
    def fm9_disconnect_blocks(row: int, col: int, to_row: int = 0, to_col: int = 0) -> dict[str, Any]:
        """Disconnect (remove cable from) the block at the given position.

        Removes the cable going from this block to its right neighbor (same row),
        or to a specific destination if to_row/to_col are provided.

        Args:
            row: Row of the source block (1-5).
            col: Column of the source block (1-14).
            to_row: Row of the destination block (1-5). If 0, defaults to same row.
            to_col: Column of the destination block (1-14). If 0, defaults to col+1.

        Returns success status.
        """
        try:
            ensure_connected()
            if not (1 <= row <= 5):
                return {"success": False, "error": "Row must be 1-5."}
            if not (1 <= col <= 14):
                return {"success": False, "error": "Column must be 1-14."}

            # Default: disconnect to right neighbor on same row
            if to_row == 0:
                to_row = row
            if to_col == 0:
                to_col = col + 1

            if not (1 <= to_row <= 5):
                return {"success": False, "error": "to_row must be 1-5."}
            if not (1 <= to_col <= 14):
                return {"success": False, "error": "to_col must be 1-14."}

            midi.disconnect_adjacent(row - 1, col - 1, to_row - 1, to_col - 1)
            return {"success": True, "from": {"row": row, "col": col}, "to": {"row": to_row, "col": to_col}}
        except Exception as e:
            return {"success": False, "error": str(e)}

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

            status = midi.get_status_dump()
            high_id_lookup = {}
            for eid in status.keys():
                if eid > 0x7F:
                    low7 = eid & 0x7F
                    high_id_lookup[low7] = eid

            known_blocks = {v["block_id_int"]: name for name, v in BLOCKS.items()}
            known_blocks[0x25] = "Input 1"
            known_blocks[0x2A] = "Output 1"

            grid = [[0] * 14 for _ in range(5)]
            block_map = {}

            for row in range(5):
                for col in range(14):
                    cell = raw_grid[row][col]
                    bid = cell["block_id"]
                    if bid != 0 and bid in high_id_lookup:
                        bid = high_id_lookup[bid]
                    grid[row][col] = bid

                    raw = cell["raw_32"]
                    byte2 = (raw >> 16) & 0xFF
                    byte3 = (raw >> 8) & 0xFF
                    is_shunt = byte2 == 0x08
                    cable_from = []
                    for r in range(5):
                        if byte3 & (1 << (r + 1)):
                            cable_from.append(r + 1)

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

    @mcp.tool()
    def fm9_read_graph() -> dict[str, Any]:
        """Read the current FM9 preset as a signal-flow graph.

        Returns the preset structure as blocks + connections (directed edges),
        abstracting away grid coordinates and shunts.

        Returns:
        - blocks: dict of {node_id: block_type_name} (real blocks only, no shunts)
        - connections: list of [from_node_id, to_node_id] pairs
        - layout: dict of {node_id: [row, col]} (current grid coordinates, 1-indexed)
        """
        try:
            ensure_connected()
            raw_grid = midi.read_grid_raw()
            status = midi.get_status_dump()

            # Build high-ID lookup
            high_id_lookup = {}
            for eid in status.keys():
                if eid > 0x7F:
                    high_id_lookup[eid & 0x7F] = eid

            known_blocks = {v["block_id_int"]: name for name, v in BLOCKS.items()}
            known_blocks[0x25] = "Input 1"
            known_blocks[0x2A] = "Output 1"

            # Parse grid into cells with metadata
            cells = {}  # (row, col) -> {bid, is_shunt, cable_from_rows}
            for row in range(5):
                for col in range(14):
                    cell = raw_grid[row][col]
                    bid = cell["block_id"]
                    raw32 = cell["raw_32"]
                    byte2 = (raw32 >> 16) & 0xFF
                    byte3 = (raw32 >> 8) & 0xFF
                    is_shunt = byte2 == 0x08

                    if bid != 0 and bid in high_id_lookup:
                        bid = high_id_lookup[bid]

                    cable_from_rows = []
                    for r in range(5):
                        if byte3 & (1 << (r + 1)):
                            cable_from_rows.append(r)

                    if bid != 0 or is_shunt:
                        cells[(row, col)] = {
                            "bid": bid,
                            "is_shunt": is_shunt,
                            "cable_from_rows": cable_from_rows,
                        }

            # Build graph: trace cables through shunts to find real block connections
            # For each real block that has cable inputs, trace backwards through shunts
            # to find the source real block.

            real_blocks = {}  # (row, col) -> block_name
            for (row, col), info in cells.items():
                if not info["is_shunt"] and info["bid"] != 0:
                    name = known_blocks.get(info["bid"], f"Block 0x{info['bid']:02X}")
                    real_blocks[(row, col)] = name

            # Create node IDs from block names (lowercase, no spaces)
            node_ids = {}  # (row, col) -> node_id
            name_counts = {}
            for (row, col), name in real_blocks.items():
                base_id = name.lower().replace(" ", "_").replace("/", "_")
                if base_id not in name_counts:
                    name_counts[base_id] = 0
                    node_ids[(row, col)] = base_id
                else:
                    name_counts[base_id] += 1
                    node_ids[(row, col)] = f"{base_id}_{name_counts[base_id]}"

            # Trace connections: for each cell with cable_from_rows, trace left
            # through shunts until we hit a real block.
            def trace_source(row, col):
                """Trace leftward from (row, col) to find all source real blocks."""
                info = cells.get((row, col))
                if not info or not info["cable_from_rows"]:
                    return []
                sources = []
                for src_row in info["cable_from_rows"]:
                    found = _trace_left(src_row, col - 1)
                    sources.extend(found)
                return sources

            def _trace_left(cur_row, col):
                """Walk left from (cur_row, col) through shunts to find real blocks."""
                while col >= 0:
                    info = cells.get((cur_row, col))
                    if info is None:
                        break
                    if not info["is_shunt"]:
                        # Found a real block
                        if (cur_row, col) in node_ids:
                            return [node_ids[(cur_row, col)]]
                        break
                    # It's a shunt — if it has multiple cable inputs, branch
                    if info["cable_from_rows"]:
                        if len(info["cable_from_rows"]) == 1:
                            cur_row = info["cable_from_rows"][0]
                        else:
                            # Multiple inputs to this shunt (merge point)
                            results = []
                            for r in info["cable_from_rows"]:
                                results.extend(_trace_left(r, col - 1))
                            return results
                    col -= 1
                return []

            connections = []
            for (row, col), node_id in node_ids.items():
                sources = trace_source(row, col)
                for src_id in sources:
                    connections.append([src_id, node_id])

            # Build output
            blocks_out = {nid: real_blocks[pos] for pos, nid in node_ids.items()}
            layout_out = {nid: [row + 1, col + 1] for (row, col), nid in node_ids.items()}

            return {
                "success": True,
                "blocks": blocks_out,
                "connections": connections,
                "layout": layout_out,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
