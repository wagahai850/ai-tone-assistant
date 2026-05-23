#!/usr/bin/env python3
"""Automated parameter scanner for Fractal Audio devices.

Scans all parameters in a block by PUT-ing unique values and detecting
which slider changes in the Editor via AppleScript.

Usage:
    python3 param_scanner.py --device axe3 --block 0x3A --editor "Axe-Edit III"
    python3 param_scanner.py --device fm9 --block 0x3A --editor "FM9-Edit"

Requirements:
    - Device connected via USB
    - Editor app open with the target block selected
    - macOS (AppleScript accessibility)
"""

import mido
import time
import subprocess
import json
import argparse
import sys
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))
from fm9_midi import DEVICES


class ParamScanner:
    def __init__(self, device_key: str, block_id: int, editor_process: str,
                 editor_group: str = "group 5"):
        self.device = DEVICES[device_key]
        self.model_id = self.device.model_id
        self.block_id = block_id
        self.editor_process = editor_process
        self.editor_group = editor_group
        self.outport = None
        self.inport = None
        self.unique_raw = 12345  # Unique value unlikely to be any default

    def connect(self):
        port_name = self.device.port_name
        available = mido.get_output_names()
        if port_name not in available:
            # Try fuzzy match
            matches = [p for p in available if self.device.name.lower() in p.lower()]
            if matches:
                port_name = matches[0]
            else:
                raise ConnectionError(f"Cannot find {self.device.name}. Available: {available}")
        self.outport = mido.open_output(port_name)
        self.inport = mido.open_input(port_name)
        time.sleep(0.3)
        self._flush()

    def disconnect(self):
        if self.outport:
            self.outport.close()
        if self.inport:
            self.inport.close()

    def _flush(self):
        while self.inport.poll():
            pass

    def _checksum(self, *data):
        cs = self.model_id
        for b in data:
            cs ^= b
        return (cs ^ 0x05) & 0x7F

    def get_chunks(self):
        """GET block data. Returns (chunks, block_select)."""
        self._flush()
        cs = self._checksum(0x1F, self.block_id, 0x00)
        self.outport.send(mido.Message('sysex',
            data=[0x00, 0x01, 0x74, self.model_id, 0x1F, self.block_id, 0x00, cs]))
        time.sleep(1.0)

        chunks = []
        block_select = None
        while True:
            msg = self.inport.poll()
            if msg is None:
                break
            if msg.type == 'sysex' and len(msg.data) >= 5:
                if msg.data[4] == 0x75:
                    chunks.append(list(msg.data))
                elif msg.data[4] == 0x74:
                    block_select = list(msg.data)
        return chunks, block_select

    def put_chunks(self, chunks, block_select):
        """PUT block data back to device."""
        self.outport.send(mido.Message('sysex', data=block_select))
        time.sleep(0.02)
        for c in chunks:
            self.outport.send(mido.Message('sysex', data=c))
            time.sleep(0.02)
        cs = self._checksum(0x76)
        self.outport.send(mido.Message('sysex',
            data=[0x00, 0x01, 0x74, self.model_id, 0x76, cs]))
        time.sleep(0.3)
        self._flush()

    # Tab coordinates for Axe-Edit III (from AppleScript position query)
    # Format: {tab_name: (center_x, center_y)}
    TAB_COORDS = {
        "Tone": (310, 761),
        "Ideal": (310, 806),
        "Preamp": (310, 851),
        "Power Amp": (310, 896),
        "Pwr Tubes + CF": (310, 941),
        "Power Supply": (310, 986),
        "Speaker": (310, 1031),
        "Input EQ": (310, 1076),
        "Output EQ": (310, 1121),
        "Dynamics": (310, 1167),
    }

    TAB_NAMES = ["Tone", "Ideal", "Preamp", "Power Amp", "Pwr Tubes + CF",
                 "Power Supply", "Speaker", "Input EQ", "Output EQ", "Dynamics"]

    def _refresh_tab_coords(self):
        """Dynamically get tab coordinates from Editor via AppleScript."""
        script = f'''
tell application "System Events"
    tell process "{self.editor_process}"
        set output to ""
        repeat with elem in (every UI element of {self.editor_group} of window 1)
            try
                if class of elem is static text then
                    set elemVal to value of elem
                    set pos to position of elem
                    set sz to size of elem
                    set output to output & elemVal & "|" & (item 1 of pos) & "|" & (item 2 of pos) & "|" & (item 1 of sz) & "|" & (item 2 of sz) & "|||"
                end if
            end try
        end repeat
        return output
    end tell
end tell'''
        result = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=15)
        for entry in result.stdout.strip().split("|||"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("|")
            if len(parts) >= 5 and parts[0] in self.TAB_NAMES:
                x = int(parts[1]) + int(parts[3]) // 2
                y = int(parts[2]) + int(parts[4]) // 2
                self.TAB_COORDS[parts[0]] = (x, y)
        print(f"  Tab coordinates refreshed: {len(self.TAB_COORDS)} tabs found")

    def read_all_sliders(self, tabs=None):
        """Read all sliders from Editor via AppleScript.
        Returns dict of {slider_name: value_string}."""
        if tabs is None:
            tabs = ["Tone"]  # Default to current tab only

        all_sliders = {}
        for tab in tabs:
            # Click tab via cliclick
            self._click_tab(tab)
            time.sleep(0.3)
            # Read sliders
            sliders = self._read_sliders()
            for name, value in sliders.items():
                all_sliders[f"{tab}/{name}"] = value

        return all_sliders

    def _click_tab(self, tab_name: str):
        """Click a tab in the Editor using cliclick (coordinate-based)."""
        coords = self.TAB_COORDS.get(tab_name)
        if coords:
            subprocess.run(['cliclick', f'c:{coords[0]},{coords[1]}'],
                         capture_output=True, timeout=5)
        else:
            print(f"WARNING: No coordinates for tab '{tab_name}'")

    def _read_sliders(self):
        """Read all sliders from current view."""
        script = f'''
tell application "System Events"
    tell process "{self.editor_process}"
        set output to ""
        repeat with elem in (every UI element of {self.editor_group} of window 1)
            try
                if class of elem is slider then
                    set output to output & (name of elem) & "|||"
                end if
            end try
        end repeat
        return output
    end tell
end tell'''
        result = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=15)
        sliders = {}
        if result.stdout.strip():
            for entry in result.stdout.strip().split("|||"):
                entry = entry.strip()
                if entry and ":" in entry:
                    parts = entry.split(":", 1)
                    name = parts[0].strip()
                    value = parts[1].strip().split(",")[0].strip()
                    sliders[name] = value
        return sliders

    def _set_amp_type(self, type_id: int):
        """Change Amp Type via sub=0x09 (same as MCP server's set_amp_type)."""
        id_lo = type_id & 0x7F
        id_hi = (type_id >> 7) & 0x7F
        id_msb = (type_id >> 14) & 0x7F

        payload = [0x01, 0x09, 0x00, self.block_id, 0x00, 0x0A, 0x00,
                   0x00, 0x00, id_lo, id_hi, id_msb, 0x00, 0x00, 0x00, 0x00]
        cs = self.model_id
        for b in payload:
            cs ^= b
        cs = (cs ^ 0x05) & 0x7F
        payload.append(cs)

        self.outport.send(mido.Message('sysex',
            data=[0x00, 0x01, 0x74, self.model_id] + payload))
        time.sleep(1.0)
        self._flush()
        print(f"  Amp Type set to ID {type_id}")

    def scan_chunk(self, chunk_idx: int, tabs: list[str], output_file: str = None):
        """Scan all params in a chunk."""
        print(f"\n{'='*60}")
        print(f"Scanning chunk {chunk_idx} of block 0x{self.block_id:02X}")
        print(f"{'='*60}")

        # Refresh tab coordinates
        self._refresh_tab_coords()

        # GET baseline
        orig_chunks, block_select = self.get_chunks()
        if not orig_chunks or not block_select:
            print("ERROR: Failed to GET block data")
            return {}

        num_params = (len(orig_chunks[chunk_idx]) - 8) // 3  # header=7, checksum=1
        print(f"Chunk {chunk_idx}: {num_params} params")

        # Read baseline sliders
        print("Reading baseline sliders...")
        baseline = self.read_all_sliders(tabs)
        print(f"  Found {len(baseline)} sliders")

        # Scan each param
        results = {}
        unique_bytes = [self.unique_raw & 0x7F, (self.unique_raw >> 7) & 0x7F,
                       (self.unique_raw >> 14) & 0x7F]

        for idx in range(num_params):
            offset = 7 + idx * 3

            # Skip if already unique value
            orig_val = orig_chunks[chunk_idx][offset:offset+3]
            if orig_val == unique_bytes:
                continue

            # Modify
            test_chunks = [list(c) for c in orig_chunks]
            test_chunks[chunk_idx][offset:offset+3] = unique_bytes

            # Recalc checksum
            cs = 0
            for b in test_chunks[chunk_idx][3:-1]:
                cs ^= b
            test_chunks[chunk_idx][-1] = (cs ^ 0x05) & 0x7F

            # PUT
            self.put_chunks(test_chunks, block_select)
            time.sleep(0.2)

            # Read sliders
            current = self.read_all_sliders(tabs)

            # Diff
            changed = {}
            for key in baseline:
                if key in current and current[key] != baseline[key]:
                    changed[key] = {"before": baseline[key], "after": current[key]}

            if changed:
                results[idx] = {
                    "offset": [offset, offset + 3],
                    "changed_sliders": changed
                }
                # Print finding
                for slider, vals in changed.items():
                    print(f"  param[{idx}] (offset [{offset}:{offset+3}]) → {slider}: {vals['before']} → {vals['after']}")

            # Restore every 10 params to prevent drift
            if idx % 10 == 9:
                self.put_chunks(orig_chunks, block_select)
                time.sleep(0.2)

            # Progress
            if idx % 25 == 24:
                print(f"  ... scanned {idx+1}/{num_params}")

        # Final restore
        self.put_chunks(orig_chunks, block_select)

        # Save results
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to {output_file}")

        print(f"\nFound {len(results)} mapped params in chunk {chunk_idx}")
        return results


def main():
    parser = argparse.ArgumentParser(description="Fractal Audio parameter scanner")
    parser.add_argument("--device", default="axe3", choices=list(DEVICES.keys()))
    parser.add_argument("--block", default="0x3A", help="Block ID (hex)")
    parser.add_argument("--editor", default="Axe-Edit III", help="Editor process name")
    parser.add_argument("--group", default="group 5", help="AppleScript UI group")
    parser.add_argument("--chunk", type=int, default=0, help="Chunk index to scan")
    parser.add_argument("--tabs", nargs="+", default=["Tone", "Ideal", "Preamp", "Power Amp",
                        "Pwr Tubes + CF", "Power Supply", "Speaker", "Input EQ", "Output EQ", "Dynamics"],
                        help="Editor tabs to scan")
    parser.add_argument("--output", default=None, help="Output JSON file")
    parser.add_argument("--amp-types", nargs="+", default=None,
                        help="Amp model names to scan (scans each sequentially)")
    args = parser.parse_args()

    block_id = int(args.block, 16) if args.block.startswith("0x") else int(args.block)

    scanner = ParamScanner(args.device, block_id, args.editor, args.group)
    scanner.connect()

    try:
        if args.amp_types:
            # Multi-model scan
            import json as json_mod
            amp_types_file = Path(__file__).parent / "fm9_amp_types.json"
            with open(amp_types_file) as f:
                amp_types_db = json_mod.load(f)
            # Build name -> id lookup
            name_to_id = {}
            for id_str, name in amp_types_db.items():
                if name not in name_to_id:
                    name_to_id[name] = int(id_str)

            for amp_name in args.amp_types:
                type_id = name_to_id.get(amp_name)
                if type_id is None:
                    # Fuzzy match
                    matches = [(n, i) for n, i in name_to_id.items() if amp_name.lower() in n.lower()]
                    if len(matches) == 1:
                        amp_name, type_id = matches[0]
                    else:
                        print(f"ERROR: Amp type '{amp_name}' not found. Skipping.")
                        continue

                print(f"\n{'#'*60}")
                print(f"# Scanning with Amp Type: {amp_name} (ID={type_id})")
                print(f"{'#'*60}")

                # Change amp type via sub=0x09
                scanner._set_amp_type(type_id)
                time.sleep(1.0)

                output = f"scan_{args.device}_0x{block_id:02X}_{amp_name.replace(' ', '_').replace('+', 'plus')}_chunk{args.chunk}.json"
                scanner.scan_chunk(args.chunk, args.tabs, output)

        else:
            # Single scan
            if not args.output:
                args.output = f"scan_{args.device}_0x{block_id:02X}_chunk{args.chunk}.json"
            scanner.scan_chunk(args.chunk, args.tabs, args.output)

    finally:
        scanner.disconnect()

    print(f"\nAll scans complete!")


if __name__ == "__main__":
    main()
