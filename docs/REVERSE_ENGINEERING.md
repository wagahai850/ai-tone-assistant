# Reverse Engineering Guide

How to map new block parameters and extend the FM9 Tone Assistant.

## Prerequisites

- FM9 connected via USB
- FM9 Editor running (Mac recommended for AppleScript automation)
- Python 3 with `mido` + `python-rtmidi`
- For protocol capture: Windows + Wireshark + USBPcap

## Core Concepts

### SysEx Message Format

All FM9 communication uses Fractal Audio SysEx:

```
F0 00 01 74 [model_id] [func] [payload...] [checksum] F7
```

- Manufacturer ID: `00 01 74` (Fractal Audio)
- Model ID: `0x12` (FM9), `0x10` (Axe-Fx III), `0x11` (FM3)
- Checksum: `XOR(model_id, func, payload_bytes...) ^ 0x05 & 0x7F`

### Parameter Encoding

All parameter values use 21-bit encoding in 3 bytes (7-bit each):

```python
def encode(display_value, display_max):
    raw = int(round(display_value / display_max * 65534))
    return [raw & 0x7F, (raw >> 7) & 0x7F, (raw >> 14) & 0x7F]

def decode(lo, hi, msb, display_max):
    return (lo | (hi << 7) | (msb << 14)) / 65534 * display_max
```

### GET → MODIFY → PUT Flow

To change any block parameter:

1. **GET**: Send `func 0x1F` with block_id → FM9 responds with `func 0x74` (block select) + `func 0x75` × N (data chunks) + `func 0x76` (commit)
2. **MODIFY**: Change bytes in the data chunks at the correct offset
3. **PUT**: Send back the `func 0x74` header (from GET response) + modified `func 0x75` chunks + `func 0x76`

```python
# GET
outport.send(sysex([0x1F, block_id, 0x00, checksum]))
# Response: func 0x74 + func 0x75 × N + func 0x76

# MODIFY chunk[0] at offset
chunks[0][offset:offset+3] = encode(value, max)

# Recalculate checksum
chunks[0][-1] = recalc_checksum(chunks[0])

# PUT
outport.send(block_select_from_get)  # func 0x74
for chunk in chunks:
    outport.send(chunk)              # func 0x75
outport.send(commit)                 # func 0x76
```

## How to Map a New Block's Parameters

### Method 1: AppleScript Scanner (Mac, Automated)

The fastest method. Requires FM9 Editor on Mac.

1. Open FM9 Editor, select the block you want to map
2. Run `full_tab_scan.py` with the block_id:
   ```bash
   python full_tab_scan.py --block 0x46  # Delay 1
   ```
3. The scanner will:
   - Write a unique value to each param index (0-255)
   - Read all Editor tabs via AppleScript to find which slider changed
   - Output a JSON map of `{param_name: {idx, offset, max, type}}`

**Time:** ~30 minutes per block (256 params × 4+ tabs)

### Method 2: Manual Diff (Any Platform)

1. In FM9 Editor, set a parameter to a unique value (e.g., Bass = 7.77)
2. GET the block data:
   ```python
   chunks = midi.get_block_data(block_id)
   ```
3. Search for the encoded value:
   ```python
   target = encode(7.77, 10.0)  # [0x61, 0x65, 0x02]
   for i in range(0, len(chunks[0])-2, 3):
       if chunks[0][i:i+3] == target:
           print(f"Found at offset {i}, param_idx = {(i-7)//3}")
   ```
4. Record the mapping in the block's JSON file

### Method 3: Wireshark Capture (Windows, requires admin privileges)

For discovering new commands or understanding Editor behavior.
USBPcap needs administrator access to capture USB traffic.

1. Connect FM9 to Windows via USB
2. Start USBPcap capture (admin required):
   ```powershell
   & "C:\Program Files\USBPcap\USBPcapCMD.exe" -d '\\.\USBPcap1' -A -o "capture.pcapng"
   ```
3. Perform the operation in FM9 Editor
4. Stop capture (Ctrl+C)
5. Analyze with `parse_capture.py`:
   ```bash
   python parse_capture.py capture.pcapng --compact
   ```

## Block ID Discovery

### Finding a Block's Effect ID

Use STATUS DUMP (`func 0x13`):
```python
status = midi.get_status_dump()
# Returns: {effect_id: {bypass, channel}, ...}
```

Toggle bypass on the target block in Editor, then compare STATUS DUMP before/after.

### Block IDs > 0x7F

Some blocks (Gate=0x92, Rotary=0x82) have IDs exceeding 7-bit MIDI range. These are stored in the grid as `id & 0x7F` and must be cross-referenced with STATUS DUMP for full resolution.

## Grid Layout (sub=0x2E)

### Query

```python
# Send sub=0x2E query (23 bytes)
query = [0x00, 0x01, 0x74, 0x12, 0x01, 0x2E, 0x00, 0x00, 0x00, 0x00, 0x00,
         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x38]
# Response: 753 bytes
```

### Decoding

The grid region starts at byte offset 361 (11 header + 350 pre-grid data).

Each cell = 32 bits in a continuous 7-bit bitstream:
```
cell_start_bit = 46 + col * 192 + row * 32
```

Cell structure (32 bits):
```
bits 0-7:   block_id << 1 (7-bit block_id + LSB flag)
bits 8-15:  0x08 if shunt, 0x00 if real block
bits 16-23: cable input bitmask (bit N+1 = input from row N)
bits 24-31: reserved (0x00)
```

## Enum Scanning (Amp/Drive Models)

### AppleScript + MIDI Method

1. Write a model ID to the block's Type parameter
2. Read the model name from Editor via AppleScript
3. Repeat for all valid IDs

See `fm9_amp_enum_scan.py` and `fm9_enum_scan.py` for working implementations.

### Amp Type Command

```
sub=0x09, block_id, param=0x0A, value=type_id (21-bit)
```

### Drive Type

Written directly to param[0] of the Drive block via GET→MODIFY→PUT.

## File Structure

```
fm9_tone_assistant/
├── server.py              # MCP server (FastMCP, stdio transport)
├── fm9_midi.py            # MIDI communication layer (singleton)
├── fm9_amp_types.json     # 331 amp models {id: name}
├── fm9_drive_types.json   # 86 drive models {id: name}
├── fm9_amp_params.json    # Amp parameter map
├── fm9_drive_params.json  # Drive parameter map
├── fm9_blocks.json        # All known blocks + their params
└── run.py                 # Cross-platform launcher
```

## Tips

- **Changes are volatile until STORE**: Parameter edits and block operations take effect immediately on the DSP, but are lost on preset change unless you call `fm9_store_preset`. This is actually a safety feature — you can experiment freely without risk.
- **GET returns active channel only**: The FM9 has 4 channels (A/B/C/D) per block. GET only returns the currently active channel's data. Switch channels before reading if needed.
- **Block SELECT (func 0x74) varies per block**: The header bytes differ between Amp (5 bytes), Drive (4 bytes), Delay (4 bytes), etc. Always reuse the one from the GET response.
- **Moving blocks disconnects cables**: This is FM9 behavior, not a bug. Reconnect after move.
- **FM9 Editor can coexist**: Both the MCP server and Editor can control FM9 simultaneously via USB MIDI. No exclusive lock.
