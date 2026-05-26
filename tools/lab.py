"""Diagnostic and reverse-engineering tools (raw sysex, snapshot, diff, dump)."""

from typing import Any

from tools import midi, ensure_connected


# Internal storage for block snapshots (not persisted across restarts)
_snapshots: dict[str, dict[str, list]] = {}


def register(mcp):
    """Register lab/RE tools on the MCP server."""

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
                    "data_preview": chunk[7:37],
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
            hex_clean = hex_bytes.replace(" ", "").replace(",", "").replace("0x", "")
            if len(hex_clean) % 2 != 0:
                return {"success": False, "error": "Hex string must have even length."}
            data = [int(hex_clean[i:i+2], 16) for i in range(0, len(hex_clean), 2)]

            import mido
            import time
            with midi._midi_lock:
                midi._flush_input()
                midi._outport.send(mido.Message("sysex", data=data))

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
