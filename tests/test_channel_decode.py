#!/usr/bin/env python3
"""Test channel C/D decode — verify checksum stripping fixes the stride issue."""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from tools import midi, ensure_connected

ensure_connected()
chunks = midi.get_block_data(0x3A)  # Amp 1

print(f"Chunk count: {len(chunks)}")
for i, c in enumerate(chunks):
    print(f"  Chunk {i}: {len(c)} bytes, last byte (checksum?): 0x{c[-1]:02X}")

# Current (buggy) approach: strip 7 from subsequent chunks, keep checksum
combined_old = list(chunks[0])
for c in chunks[1:]:
    combined_old.extend(c[7:])
stride_old = (len(combined_old) - 7) // 4

# Fixed approach: strip checksum (last byte) from ALL chunks
combined_new = list(chunks[0][:-1])
for c in chunks[1:]:
    combined_new.extend(c[7:-1])
stride_new = (len(combined_new) - 7) // 4

print(f"\nOld: combined={len(combined_old)}, stride={stride_old}")
print(f"New: combined={len(combined_new)}, stride={stride_new}")
print(f"Diff: {len(combined_old) - len(combined_new)} bytes (should be {len(chunks)} checksums)")

# Test Gain (pid=11) across all channels
pid = 11
print(f"\nGain (pid={pid}) decode comparison:")
print(f"{'Ch':<4} {'Old raw':<12} {'Old val':<10} {'New raw':<12} {'New val':<10}")
for ch in range(4):
    # Old
    off_old = 7 + pid * 3 + ch * stride_old
    if off_old + 2 < len(combined_old):
        lo, hi, msb = combined_old[off_old], combined_old[off_old+1], combined_old[off_old+2]
        raw_old = lo | (hi << 7) | (msb << 14)
        val_old = raw_old / 65534.0 * 10.0
    else:
        raw_old, val_old = -1, -1

    # New
    off_new = 7 + pid * 3 + ch * stride_new
    if off_new + 2 < len(combined_new):
        lo, hi, msb = combined_new[off_new], combined_new[off_new+1], combined_new[off_new+2]
        raw_new = lo | (hi << 7) | (msb << 14)
        val_new = raw_new / 65534.0 * 10.0
    else:
        raw_new, val_new = -1, -1

    marker = " ✓" if 0 <= val_new <= 10 else " ✗"
    print(f"{ch:<4} {raw_old:<12} {val_old:<10.2f} {raw_new:<12} {val_new:<10.2f}{marker}")

# Also test Bass (pid=12) and Type (pid=10)
for name, pid in [("Type", 10), ("Bass", 12), ("Presence", 0)]:
    print(f"\n{name} (pid={pid}):")
    for ch in range(4):
        off = 7 + pid * 3 + ch * stride_new
        if off + 2 < len(combined_new):
            lo, hi, msb = combined_new[off], combined_new[off+1], combined_new[off+2]
            raw = lo | (hi << 7) | (msb << 14)
            print(f"  Ch {ch}: raw={raw}")
