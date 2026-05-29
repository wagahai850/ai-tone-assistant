"""Grid layout and routing tools (add/delete/move/connect blocks)."""

from typing import Any

from tools import BLOCK_ID_TO_NAME, BLOCK_NAME_TO_ID, midi, ensure_connected


# Known block types for add_block (user-friendly names)
# Built from BLOCK_NAME_TO_ID plus common aliases
BLOCK_TYPE_MAP: dict[str, int] = {}

# Populate from the canonical BLOCK_NAME_TO_ID map
for name, bid in BLOCK_NAME_TO_ID.items():
    BLOCK_TYPE_MAP[name] = bid
    # Add no-space alias (e.g., "Amp1" for "Amp 1")
    no_space = name.replace(" ", "")
    if no_space != name:
        BLOCK_TYPE_MAP[no_space] = bid

# Add common short aliases
_ALIASES = {
    "Comp 1": "Compressor 1", "Comp 2": "Compressor 2",
    "Comp 3": "Compressor 3", "Comp 4": "Compressor 4",
    "Comp1": "Compressor 1", "Comp2": "Compressor 2",
    "GEQ": "Graphic EQ 1", "GEQ 1": "Graphic EQ 1", "GEQ 2": "Graphic EQ 2",
    "PEQ": "Parametric EQ 1", "PEQ 1": "Parametric EQ 1", "PEQ 2": "Parametric EQ 2",
    "Gate 1": "Gate/Expander 1", "Gate 2": "Gate/Expander 2",
    "Gate1": "Gate/Expander 1", "Gate2": "Gate/Expander 2",
    "Gate/Expander 1": "Gate/Expander 1", "Gate/Expander 2": "Gate/Expander 2",
    "Multitap 1": "Multitap Delay 1", "Multitap 2": "Multitap Delay 2",
    "Multitap1": "Multitap Delay 1", "Multitap2": "Multitap Delay 2",
    "Megatap 1": "Megatap Delay 1", "Megatap 2": "Megatap Delay 2",
    "Plex 1": "Plex Delay 1", "Plex 2": "Plex Delay 2",
    "Vol/Pan 1": "Volume/Pan 1", "Vol/Pan 2": "Volume/Pan 2",
    "Ring Mod": "Ring Modulator 1",
    "Enhancer": "Enhancer 1",
    "Looper": "Looper 1",
    "Filter 1": "Filter 1", "Filter 2": "Filter 2",
}
for alias, canonical in _ALIASES.items():
    if canonical in BLOCK_NAME_TO_ID:
        BLOCK_TYPE_MAP[alias] = BLOCK_NAME_TO_ID[canonical]


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
                        name = BLOCK_ID_TO_NAME.get(bid, f"Block 0x{bid:02X}") if bid != 0 else "shunt"
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

            # Build graph: real blocks and trace connections through shunts
            real_blocks = {}  # (row, col) -> block_name
            for (row, col), info in cells.items():
                if not info["is_shunt"] and info["bid"] != 0:
                    name = BLOCK_ID_TO_NAME.get(info["bid"], f"Block 0x{info['bid']:02X}")
                    real_blocks[(row, col)] = name

            # Create node IDs from block names
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

    @mcp.tool()
    def fm9_apply_graph(blocks: dict[str, str], connections: list[list[str]]) -> dict[str, Any]:
        """Apply a signal-flow graph to the FM9 grid.

        Computes a 2D layout from the graph, clears the grid, places blocks,
        and connects cables. Block parameters are preserved across the operation.

        Args:
            blocks: Dict of {node_id: block_type_name}.
                    Example: {"in": "Input 1", "amp": "Amp 1", "out": "Output 1"}
            connections: List of [from_node_id, to_node_id] pairs.
                    Example: [["in", "amp"], ["amp", "out"]]

        Returns success status with the computed layout.
        """
        try:
            ensure_connected()

            # Validate block types using BLOCK_TYPE_MAP (includes aliases)
            name_to_id = dict(BLOCK_TYPE_MAP)

            for node_id, block_type in blocks.items():
                if block_type not in name_to_id:
                    return {"success": False, "error": f"Unknown block type '{block_type}' for node '{node_id}'."}

            # Validate connections reference valid nodes
            for conn in connections:
                if conn[0] not in blocks:
                    return {"success": False, "error": f"Connection source '{conn[0]}' not in blocks."}
                if conn[1] not in blocks:
                    return {"success": False, "error": f"Connection target '{conn[1]}' not in blocks."}

            # Compute layout: topological sort → column assignment
            from collections import defaultdict, deque
            successors = defaultdict(list)
            predecessors = defaultdict(list)
            for src, dst in connections:
                successors[src].append(dst)
                predecessors[dst].append(src)

            # Find roots (no predecessors)
            roots = [n for n in blocks if n not in predecessors]
            if not roots:
                return {"success": False, "error": "Graph has no root nodes (cycle detected?)."}

            # BFS to assign columns (longest path from any root = column)
            col_assign = {}
            queue = deque()
            for r in roots:
                col_assign[r] = 0
                queue.append(r)

            while queue:
                node = queue.popleft()
                for succ in successors[node]:
                    new_col = col_assign[node] + 1
                    if succ not in col_assign or new_col > col_assign[succ]:
                        col_assign[succ] = new_col
                        queue.append(succ)

            # Assign rows: handle parallel paths (split → merge)
            split_points = [n for n in blocks if len(successors.get(n, [])) > 1]
            merge_points = set(n for n in blocks if len(predecessors.get(n, [])) > 1)

            row_assign = {n: 0 for n in blocks}

            for split in split_points:
                # Trace each branch from split to merge
                branch_paths = {}
                for succ in successors[split]:
                    path = []
                    current = succ
                    while current and current not in merge_points:
                        path.append(current)
                        nexts = successors.get(current, [])
                        current = nexts[0] if nexts else None
                    branch_paths[succ] = path

                # Shortest branch = main row, longer branches get offset rows
                sorted_branches = sorted(branch_paths.items(), key=lambda x: len(x[1]))
                for i, (succ, path) in enumerate(sorted_branches):
                    if i == 0:
                        continue  # Shortest stays on main row
                    row_offset = -i
                    for node in path:
                        row_assign[node] = row_offset

            # Normalize rows (shift so min = 0)
            min_row = min(row_assign.values())
            for node in row_assign:
                row_assign[node] -= min_row

            # Center vertically in 5-row grid
            max_row = max(row_assign.values())
            start_row = max(0, (4 - max_row) // 2)
            for node in row_assign:
                row_assign[node] += start_row

            layout = {}  # node_id -> (row, col) 0-indexed
            for node in blocks:
                row = row_assign[node]
                col = col_assign[node]
                if row >= 5:
                    return {"success": False, "error": f"Too many parallel branches (max 5 rows)."}
                layout[node] = (row, col)

            # Check column limit (14 max)
            max_col = max(c for _, c in layout.values())
            if max_col >= 14:
                return {"success": False, "error": f"Graph requires {max_col+1} columns (max 14)."}

            # Phase 1: Clear all blocks from grid
            raw_grid = midi.read_grid_raw()
            import time as _time
            for row in range(5):
                for col in range(14):
                    cell = raw_grid[row][col]
                    bid = cell["block_id"]
                    raw32 = cell["raw_32"]
                    byte2 = (raw32 >> 16) & 0xFF
                    if bid != 0 or byte2 == 0x08:
                        midi.delete_block_at(row, col)

            # Allow device to finish processing deletions
            _time.sleep(1.0)

            # Phase 2: Place blocks (with pacing to avoid overwhelming device)
            for node_id, (row, col) in layout.items():
                block_type = blocks[node_id]
                bid = name_to_id[block_type]
                midi.add_block_at(bid, row, col)
                _time.sleep(0.15)

            # Allow device to settle after block placements
            _time.sleep(1.5)

            # Phase 3: Connect cables (paced)
            next_shunt_idx = 0

            for src, dst in connections:
                src_row, src_col = layout[src]
                dst_row, dst_col = layout[dst]
                if src_col < dst_col:
                    if src_row == dst_row:
                        # Same-row: place shunts in intermediate columns
                        for col in range(src_col + 1, dst_col):
                            midi.add_shunt_at(src_row, col, shunt_index=next_shunt_idx)
                            next_shunt_idx += 1
                        for col in range(src_col, dst_col):
                            midi.connect_adjacent(src_row, col, src_row, col + 1)
                    elif src_col + 1 == dst_col:
                        # Adjacent columns, cross-row: direct cable
                        midi.connect_adjacent(src_row, src_col, dst_row, dst_col)
                    else:
                        # Cross-row + cross-column: shunts on dst_row
                        for col in range(src_col + 1, dst_col):
                            midi.add_shunt_at(dst_row, col, shunt_index=next_shunt_idx)
                            next_shunt_idx += 1
                        midi.connect_adjacent(src_row, src_col, dst_row, src_col + 1)
                        for col in range(src_col + 1, dst_col):
                            midi.connect_adjacent(dst_row, col, dst_row, col + 1)
                elif src_col == dst_col and src_row != dst_row:
                    # Same column, different row
                    midi.connect_adjacent(src_row, src_col, dst_row, dst_col)
                _time.sleep(0.1)  # Pace each connection group

            # Build output layout (1-indexed for user)
            layout_out = {nid: [r + 1, c + 1] for nid, (r, c) in layout.items()}

            return {
                "success": True,
                "layout": layout_out,
                "blocks_placed": len(blocks),
                "connections_made": len(connections),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
