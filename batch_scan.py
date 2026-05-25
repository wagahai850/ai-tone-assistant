#!/usr/bin/env python3
"""Batch parameter scanner for multiple block types on FM9.

Scans each block type sequentially:
1. Deletes current block at R1C1
2. Adds target block at R1C1
3. Waits for Editor to select it
4. Runs param scan (auto-detects tabs)
5. Saves results and moves to next block

Usage:
    caffeinate -dims python3 -u batch_scan.py 2>&1 | tee batch_scan_log.txt

    Or with nohup:
    nohup caffeinate -dims python3 -u batch_scan.py > batch_scan_log.txt 2>&1 &
"""

import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fm9_midi import FractalMidi
from param_scanner import ParamScanner

# Blocks to scan — loaded from fm9_blocks.json, filtered to first instance of each type
# Only blocks with block_id <= 0x7F (SysEx 7-bit limit)
SCAN_BLOCKS = [
    "Amp 1",
    "Drive 1",
    "Cab 1",
    "Reverb 1",
    "Delay 1",
    "Chorus 1",
    "Compressor 1",
    "Graphic EQ 1",
    "Parametric EQ 1",
    "Flanger 1",
    "Phaser 1",
    "Wah 1",
    "Formant 1",
    "Volume/Pan 1",
    "Tremolo/Panner 1",
    "Pitch 1",
    "Filter 1",
    "Enhancer 1",
    "Rotary 1",
    "Multitap Delay 1",
    "Mixer 1",
    "Gate/Expander 1",
    "Crossover 1",
    "Megatap Delay 1",
    "Multiband Comp 1",
    "Plex Delay 1",
    "Resonator 1",
    "Synth 1",
    "Ten-Tap Delay 1",
    "Ring Modulator",
    "Looper",
]

DEVICE = "fm9"
EDITOR = "FM9-Edit"
GROUP = "group 5"


def swap_block(block_id: int, name: str):
    """Delete current R1C1 block and add new one."""
    midi = FractalMidi()
    midi._initialized = False
    midi.__init__()
    midi.configure(DEVICE)
    midi.connect()

    print(f"  Deleting R1C1...")
    midi.delete_block_at(row=0, col=0)
    time.sleep(1.0)

    print(f"  Adding {name} (0x{block_id:02X})...")
    midi.add_block_at(block_id=block_id, row=0, col=0)
    time.sleep(2.0)

    # Verify
    status = midi.get_status_dump()
    if block_id in status:
        print(f"  ✅ {name} confirmed in preset (channel={status[block_id]['channel']})")
    else:
        print(f"  ❌ {name} NOT found in status dump!")
        midi.disconnect()
        return False

    midi.disconnect()
    return True


def scan_block(block_id: int, name: str):
    """Scan a single block."""
    output_file = str(Path(__file__).parent / f"scan_fm9_{name.lower().replace(' ', '_').replace('/', '_')}_chunk0.json")

    # Skip if already scanned
    if Path(output_file).exists() and Path(output_file).stat().st_size > 10:
        print(f"  SKIPPING {name} - already scanned ({output_file} exists)")
        return

    print(f"\n{'#'*70}")
    print(f"# Scanning: {name} (0x{block_id:02X})")
    print(f"# Output: {output_file}")
    print(f"{'#'*70}")

    try:
        # Swap block
        if not swap_block(block_id, name):
            print(f"  SKIPPING {name} - failed to add")
            return

        # Wait for Editor to settle
        time.sleep(3.0)

        # Create scanner and run
        scanner = ParamScanner(DEVICE, block_id, EDITOR, GROUP)
        scanner.connect()

        try:
            scanner.scan_chunk(chunk_idx=0, tabs=None, output_file=output_file)
        finally:
            scanner.disconnect()

    except Exception as e:
        print(f"  ERROR scanning {name}: {e}")
        print(f"  SKIPPING to next block...")


def main():
    start_time = time.time()
    print(f"Batch scan starting at {time.strftime('%H:%M:%S')}")
    print(f"Device: {DEVICE}, Editor: {EDITOR}")

    # Load block IDs from fm9_blocks.json
    with open(Path(__file__).parent / "fm9_blocks.json") as f:
        all_blocks = json.load(f)

    # Build scan list
    blocks = []
    for name in SCAN_BLOCKS:
        if name in all_blocks:
            info = all_blocks[name]
            block_id = info["block_id_int"]
            blocks.append((block_id, name))
        else:
            print(f"  WARNING: {name} not found in fm9_blocks.json")

    print(f"Blocks to scan: {len(blocks)}")
    print()

    for i, (block_id, name) in enumerate(blocks):
        block_start = time.time()
        print(f"\n[{i+1}/{len(blocks)}] {name}")
        scan_block(block_id, name)
        elapsed = time.time() - block_start
        print(f"  Completed in {elapsed/60:.1f} min")

    total = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"Batch complete! Total time: {total/60:.1f} min ({total/3600:.1f} hours)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
