# Reverse Engineering Guide

How parameter maps and model databases were built for the FM9 Tone Assistant.

## Methodology Overview

All protocol knowledge was obtained through **observing USB MIDI traffic** between the FM9 and its official Editor application, combined with **reading the Editor's local cache files** (JSON/XML stored on disk by the Editor for its own use).

No firmware was modified. No copy protection was circumvented.

### Techniques Used

| Method | What it reveals | Tools |
|--------|----------------|-------|
| USB MIDI traffic capture | SysEx message format, command structure | Wireshark + USBPcap (Windows) |
| MIDI port sniffing | Device broadcast messages, response formats | Python + mido |
| Editor cache parsing | Parameter names, model names, type definitions | Python (JSON/XML parsing) |
| Differential analysis | Parameter offsets (change value → observe byte diff) | Python scripts |
| AppleScript UI reading | Parameter display names, slider values | macOS Accessibility API |

### What was NOT done

- No firmware dumping or modification
- No DRM/copy-protection circumvention
- No distribution of proprietary data (model names are publicly documented on the Fractal Wiki)

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

1. **GET**: Send `func 0x1F` with block_id → FM9 responds with block data chunks
2. **MODIFY**: Change bytes at the correct offset
3. **PUT**: Send back the modified chunks with proper headers

## How Parameters Were Mapped

### Method 1: Differential Analysis (Primary)

1. Set a parameter to a known unique value in the Editor
2. GET the block data via MIDI
3. Search for the encoded value in the response
4. Record the offset → parameter name mapping

This was automated with AppleScript (to read Editor UI) + Python (to send/receive MIDI).

### Method 2: Editor Cache Parsing

The FM9 Editor stores parameter definitions locally as part of its normal operation. These files contain:
- Parameter names and their internal identifiers
- Effect type/model name lists
- Type-specific parameter visibility rules

Parsing these files provided the complete parameter name database (1321 parameters across 40 blocks) without needing to scan each one individually on hardware.

### Method 3: USB Traffic Observation

For discovering command formats (grid operations, preset management, etc.), USB traffic between the Editor and FM9 was captured and analyzed to understand the message structure.

## Block ID Discovery

Use STATUS DUMP (`func 0x13`) to see which blocks are present:
```python
status = midi.get_status_dump()
# Returns: {effect_id: {bypass, channel}, ...}
```

Toggle bypass on a block in Editor, compare before/after to identify its ID.

## Enum Scanning (Amp/Drive Models)

Model names were obtained by:
1. Writing each model ID to the block's Type parameter via MIDI
2. Reading the resulting model name from the Editor UI via AppleScript
3. Cross-referencing with the publicly available Fractal Wiki

## Data Pipeline

```bash
# After firmware update, regenerate data:
python3 pipeline/pipeline_params.py fm9       # Extract param tables
python3 pipeline/pipeline_effect_defs.py fm9  # Extract model/type names
python3 pipeline/enrich_params.py             # Add min/max metadata
python3 pipeline/build_wiki_data.py --fetch   # Update Wiki reference
```

## File Structure

```
ai-tone-assistant/
├── server.py              # MCP server entry point (FastMCP, stdio)
├── fractal_midi.py        # MIDI communication layer (device-agnostic singleton)
├── tools/                 # MCP tool definitions (by category)
│   ├── __init__.py        # Shared state, data loading, encoding helpers
│   ├── amp_drive.py       # Amp/Drive (display-value scaling)
│   ├── generic_block.py   # Any block (normalized 0-1, meta-aware)
│   ├── grid_routing.py    # Grid layout operations
│   ├── preset.py          # Scene/bypass/channel/store/name
│   ├── lookup.py          # Wiki reference search
│   └── lab.py             # RE/debug (raw sysex, snapshot, diff)
├── data/fm9/              # Runtime data (JSON, committed)
│   ├── all_params.json    # 1321 params with meta (type/min/max/verified)
│   ├── amp_params.json    # Amp 1: 74 hand-verified params
│   ├── drive_params.json  # Drive 1: 28 hand-verified params
│   ├── amp_types.json     # 331 amp models {id: name}
│   ├── drive_types.json   # 86 drive models {id: name}
│   ├── blocks.json        # 137 block IDs
│   ├── effect_definitions.json  # All model/type names
│   ├── type_valid_params.json   # Type-specific valid params
│   ├── wiki_models.json   # Wiki amp/drive model info
│   └── wiki_blocks.json   # Wiki effect block info
├── pipeline/              # RE/extraction scripts (.gitignore'd)
├── docs/
│   ├── PROTOCOL.md        # SysEx protocol reference
│   └── REVERSE_ENGINEERING.md  # This file
└── README.md
```

## Tips

- **Changes are volatile until STORE**: Parameter edits take effect immediately on the DSP but are lost on preset change unless you call `fm9_store_preset`.
- **GET returns active channel only**: FM9 has 4 channels (A/B/C/D) per block. GET returns the currently active channel's data.
- **Block SELECT header varies per block**: Always reuse the one from the GET response.
- **Moving blocks disconnects cables**: FM9 behavior, not a bug. Reconnect after move.
- **FM9 Editor can coexist**: Both the MCP server and Editor can control FM9 simultaneously via USB MIDI.
- **Block IDs > 0x7F**: Use 2-byte encoding `[id & 0x7F, (id >> 7) & 0x7F]` in SysEx messages.
- **Shunt index must be unique**: When placing multiple shunts (cable pass-throughs), each one needs a unique sequential index in the sub=0x32 payload byte[3]. Sending the same index twice causes the FM9 to silently reject the second placement. Query the grid to find the current max index before adding new shunts.

## Notable Discoveries

### Shunt Sequential Index (2026-05-26)

**Symptom**: `add_shunt_at` succeeded on the first call but silently failed on subsequent calls within the same preset. Normal block placement (`add_block_at`) worked reliably in any quantity.

**Root cause**: The sub=0x32 message for shunt placement has a sequential index field at byte[3] that must be unique per preset. Our code was sending 0x00 for every shunt, causing the FM9 to reject duplicates.

**Discovery method**: USB traffic capture (Wireshark + USBPcap on Windows) of FM9 Editor performing a multi-shunt cable connection. The capture revealed:

```
Shunt 1: sub=0x32 byte[3]=0x00, byte[4]=0x08
Shunt 2: sub=0x32 byte[3]=0x01, byte[4]=0x08
Shunt 3: sub=0x32 byte[3]=0x02, byte[4]=0x08
Shunt 4: sub=0x32 byte[3]=0x03, byte[4]=0x08
```

**Fix**: Read the grid before placing shunts, find the maximum existing shunt index, and increment from there.
