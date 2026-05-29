# Pipeline: Reverse Engineering & Data Extraction

Tools for extracting parameter data from Fractal Audio Editor binaries and firmware caches.
This is the single source of truth for RE methodology. The Obsidian notes are historical only.

## Data Source Matrix

What information comes from where, and what tool extracts it.

| Information | Source | Method | Tool | Status |
|-------------|--------|--------|------|--------|
| SysEx protocol (commands, checksum) | Editor ↔ FM9 USB traffic | Wireshark + USBPcap (Windows) | `parse_pcap.py` | ✅ Confirmed |
| block_id (137 blocks) | FM9 hardware | STATUS DUMP (func=0x13) | `fractal_midi.py` | ✅ Confirmed |
| param_id (internal name → pid) | Editor binary (arm64) | Ghidra static analysis | `pipeline_params.py` | ✅ 40 blocks × 1395 params |
| Model/type names | effectDefinitions cache | String section parsing | `pipeline_effect_defs.py` | ✅ All blocks |
| min / max / step / type | effectDefinitions cache | Format A (float 1.0 marker) for real display max; Block-based for type/flags | `parse_cache_sequential.py` (Format A, 761 params) / `extracted/parse_cache_full.py` (block-based, WIP) | 🔄 Format A verified for AMP; block-matching to all_params.json not yet automated |
| Type-specific valid params | Editor binary XML | ZIP-embedded XML parsing | `pipeline_params.py` (XML extraction) | △ Amp only; other blocks lack XML data |
| FM9-Edit embedded resources | Editor binary (universal) | ZIP extraction from Mach-O | `extracted/` scripts | ✅ `__block_layout.xml` (1.16MB), `__components.xml` extracted |
| Encoding (normalized vs raw_float) | Editor ↔ FM9 USB traffic | Wireshark capture + roundtrip test | `parse_pcap.py` + `tests/calibrate_decode.py` | ✅ All block types confirmed (2026-05-29) |
| Bipolar actual range | Round-trip test | SET → GET comparison | `tests/calibrate_decode.py` | ✅ Delay 1, Reverb 1 calibrated |
| GET decode_max (internal storage max) | FM9 hardware | SET known value → GET raw → compute | `tests/calibrate_decode.py` | 🔄 Delay 1 + Reverb 1 done; other blocks pending |
| Type-specific valid params (non-Amp) | FM9 hardware | SET and check raw change | `tests/test_roundtrip.py` (skip logic) | ❌ No static source |
| type_id ↔ model name mapping | FM9 + Editor UI | AppleScript + MIDI SysEx | enum scanner scripts | ✅ Amp 331 + Drive 86 |

## Static vs Hardware-Required

| Category | Static (binary/cache) | Hardware required |
|----------|----------------------|-------------------|
| param_id | ✅ Ghidra | — |
| min/max (display) | ✅ Cache (80%) | — |
| decode_max (internal) | — | ✅ Roundtrip calibration |
| decode_style | — | ✅ Roundtrip calibration |
| type classification | ✅ Cache flags | — |
| Encoding rules | — | ✅ Wireshark (once per block type) |
| Type-specific valid params | △ Amp only (XML) | ✅ Other blocks need live test |
| Model names | ✅ Cache | — |
| type_id mapping | ✅ Cache (index order) | Verified via AppleScript |

## Scripts

### Parameter Extraction (from Editor binary)

| Script | Input | Output | Description |
|--------|-------|--------|-------------|
| `pipeline_params.py` | Editor .app binary | `all_params.json` | Extract param tables (name, param_id) via Ghidra-derived offsets. Also extracts type-valid params from embedded XML. |
| `pipeline_effect_defs.py` | Editor firmware cache | `effect_definitions.json` | Extract model/type names from Editor's effectDefinitions cache. |
| `parse_cache_sequential.py` | effectDefinitions cache | `cache_params.json` | **Legacy**: Extract min/max/step/type using Format A (float 1.0 marker) heuristic. Found 1276 params but misses blocks like Delay. |
| `parse_cache_full.py` | effectDefinitions cache | `cache_parsed_full.json` | **New**: Block-based parser using correct structure (block headers + enum detection). Parses Block 0 fully; remaining blocks need block-boundary scanner. |
| `apply_cache_to_all_params.py` | `cache_params.json` + `all_params.json` | `all_params.json` (updated) | Match cache records to blocks by param_id sequence, update min/max/type. Uses legacy cache_params.json. |
| `enrich_params.py` | `all_params.json` + scan data | `all_params.json` (enriched) | Legacy: pattern-match type/min/max. Superseded by cache parser for most params. |

### Scanning (live device)

| Script | Input | Output | Description |
|--------|-------|--------|-------------|
| `param_scanner.py` | Live FM9 + Editor | `scan_fm9_{block}_chunk0.json` | Set each param via SysEx, read Editor UI via AppleScript. Requires FM9-Edit open. |
| `batch_scan.py` | Live FM9 + Editor | Multiple scan JSONs | Batch-run param_scanner across blocks. |

### Capture Analysis

| Script | Input | Output | Description |
|--------|-------|--------|-------------|
| `parse_pcap.py` | `.pcapng` (Wireshark) | Decoded SysEx (stdout) | Decode USB-MIDI captures. Shows SET_PARAM, NOTIFY, SLIDE with float values. Requires `tshark`. |

```bash
# Cab 1 SET messages only
python3 pipeline/parse_pcap.py capture.pcapng --block 0x3E --no-notify

# All blocks, all subs
python3 pipeline/parse_pcap.py capture.pcapng
```

### Wiki Data

| Script | Input | Output | Description |
|--------|-------|--------|-------------|
| `build_wiki_data.py` | wiki.fractalaudio.com | `wiki_models.json`, `wiki_blocks.json` | Fetch Fractal Wiki for model info. Requires `pandoc`. |

### Exploratory / Debug

| Script | Description |
|--------|-------------|
| `analyze_cache_structure.py` | Inspect effectDefinitions cache binary structure |
| `extract_enums.py` | Extract enum values from Editor binary |
| `extract_types.py` | Extract effect type lists from firmware cache |
| `verify_scan_vs_enum.py` | Cross-reference scan results with Editor enum data |
| `capture_startup.py` | Capture Editor startup SysEx sequence |
| `capture_type_change.py` | Capture SysEx when changing effect type |

## Workflows

### Firmware Update

```
1. Connect FM9 to Editor (generates new effectDefinitions cache)
2. python3 pipeline/parse_cache_v5.py --apply
   → Updates all_params.json with new param definitions from cache
3. python3 tests/calibrate_decode.py --all --apply
   → Measures correct decode_max for GET decode (requires FM9 connected)
4. python3 -u tests/test_roundtrip.py 2>&1 | tee tests/roundtrip_log.txt
   → Verify SET→GET roundtrip integrity
5. Restart MCP server to pick up changes
```

### Calibrate GET Decode (after any all_params.json change)

```
# Single block:
python3 tests/calibrate_decode.py --block "Delay 1" --apply

# All effect blocks (~5 min, requires FM9):
python3 tests/calibrate_decode.py --all --apply

# Dry run (show what would change):
python3 tests/calibrate_decode.py --block "Reverb 1" --dry-run
```

The calibration script:
1. Places the block on the grid (if not already present)
2. For each non-enum/switch param: SET 0 → read raw (determines decode_style)
3. SET 50% of max → read raw (determines decode_max)
4. Records `decode_max` and `decode_style` in all_params.json
5. Removes the block from grid (if it was placed by the script)

### Roundtrip Verification

```
# Test specific block:
python3 tests/test_roundtrip.py --block "Delay 1"

# Test all blocks:
python3 tests/test_roundtrip.py

# Classify failures:
python3 tests/classify_failures.py
```

### Axe-Fx III / FM3 Support

```
1. Extract Axe-Edit III (or FM3-Edit) arm64 binary
2. Ghidra: find param table (same structure, different offsets)
3. python3 pipeline/pipeline_params.py axe3
4. python3 pipeline/pipeline_effect_defs.py axe3
5. python3 pipeline/parse_cache_sequential.py --cache ~/Library/.../Axe-Edit III/effectDefinitions_10_*.cache
6. python3 pipeline/apply_cache_to_all_params.py --device axe3
7. Wireshark: verify encoding rules (expected same as FM9)
8. Deploy to data/axe3/
```

### New Block Type (after firmware adds one)

```
1. STATUS DUMP to get new block_id
2. Ghidra: check if param table has new entries
3. If not in Ghidra table: use param_scanner.py (live scan)
4. Add to blocks.json manually
5. Run cache parser to get min/max
6. Round-trip test to verify
```

## effectDefinitions Cache Structure

File: `~/Library/Application Support/Fractal Audio/{Editor}/effectDefinitions_{model}_{version}.cache`

Generated by FM9-Edit on first connection to FM9. Contains parameter definitions
queried from firmware via SysEx (func 0x17 "Query All Param Definitions").

### Overall Layout

```
[Header: 42 bytes]
[Block 0: header + params]
[Block 1: header + params]
...
[Block N: header + params]
[Preset names section]
[Cab names section]
[... other data ...]
```

### Header (0x00–0x29)

```
+0x00: uint32 LE  firmware_major (e.g., 11)
+0x04: uint32 LE  firmware_minor (e.g., 0)
+0x08: uint16 LE  unknown (4)
+0x0A: char[20]   build_date ("May 30 2025 12:40:41")
+0x1E: padding    (zeros to 0x29)
```

### Block Structure

Each block starts with an 8-byte header, followed by parameter records:

```
[uint32 LE] block_id      (internal cache block ID, NOT SysEx block_id)
[uint32 LE] num_params    (number of parameter records in this block)
[param records × num_params]
```

**Block boundary detection**: Block headers appear immediately after the previous
block's last enum trailer (`00 80 00 00 00 00`) or after 10+ zero bytes (end of
continuous record padding). 38 block headers confirmed at known offsets.

**Block 0** (id=1): Global/System settings, 225 params. Contains MIDI CC assignments,
global EQ, I/O routing, etc.

### Continuous/Bipolar/Frequency Records (32 bytes)

```
+0:  uint16 LE  param_index   (sequential within block)
+2:  uint16 LE  flags         (type indicator, always > 0x001F)
+4:  uint32 LE  reserved      (always 0)
+8:  uint16 LE  raw_default?  (possibly default raw value)
+10: uint16 LE  padding       (always 0)
+12: uint16 LE  raw_unknown   (possibly related to display)
+14: float LE   max           (display maximum) ← CONFIRMED
+18: float LE   step          (display step, 0 = auto) ← CONFIRMED
+22: 10 bytes   zeros/reserved
```

### Flags → Type Mapping

| Flag pattern | Type | Description |
|---|---|---|
| `0x0531` | bipolar | Signed range (e.g., -100 to +100) |
| `0x0231` | frequency | Log-scale frequency (e.g., 20–20000 Hz) |
| `0x0032` | continuous | Linear 0 to max |
| `0x0062` | continuous | Linear 0 to max (variant) |
| `0x0732` | frequency | Log-scale frequency (variant) |
| `0x0132` | bipolar | Signed range (variant) |
| `0x0242` | frequency | Log-scale frequency (variant) |
| `0x0010` | enum | (see below) |
| `0x0020` | enum | (see below, large enum like CC#) |

**Bit interpretation** (partial):
- bit 8 (`0x0100`): bipolar
- bit 9 (`0x0200`): frequency

### Enum/Switch Records (variable length)

```
+0:  uint16 LE  param_index
+2:  uint16 LE  flags         (≤ 0x0020 for enum)
+4:  18 bytes   fixed data    (mostly zeros, +12 may contain f32 max)
+22: uint32 LE  num_enum_values
+26: [uint32 LE strlen + char[strlen]] × num_enum_values
+N:  6 bytes    trailer       (00 80 00 00 00 00)
```

**Enum detection heuristic**: `uint32 at offset+22` is 1–500 AND `uint32 at offset+26`
(first string length) is 1–100.

### Legacy Format A (float 1.0 marker) — PRIMARY DATA SOURCE

The parser `parse_cache_sequential.py` scans for 32-byte records with `float 1.0`
at offset +4. This reliably extracts 761 records with **actual display max/min values**.

**Status: ✅ CONFIRMED** — AMP params (Gain=10, Bass=10, etc.) match hand-verified values.

#### Format A Record Structure (32 bytes)

Identified by `float 1.0` at offset +4, with `uint32 0` at both +12 and +16:

```
+0:  float LE   max           (ACTUAL display maximum, e.g., 16000, 20000) ← CONFIRMED (AMP)
+4:  float LE   1.0           (constant marker for identification)
+8:  float LE   step          (display step)
+12: uint32 LE  0             (must be zero — validation)
+16: uint32 LE  0             (must be zero — validation)
+20: uint32 LE  id_raw        (param_id at bits 16-23, block_idx at bits 24-31)
+24: uint32 LE  flags         (type indicator)
+28: float LE   min           (display minimum, e.g., -80.0 for Level)
```

**Extracting param_id**: `param_id = (id_raw >> 16) & 0xFF` — ✅ CONFIRMED (AMP Gain pid=11)
**Extracting block_idx**: `block_idx = (id_raw >> 24) & 0xFF` — mostly 0, not useful for block ID

#### Format A Block Boundaries

Records are ordered by block. Block boundaries detected where param_id resets
(decreases significantly). 34 blocks detected in sequence.

**Verified**: AMP block — pid=11 (Gain) max=10.0 ✓, pid=12 (Bass) max=10.0 ✓
**Not in Format A**: Delay Time (pid=12, max=16000) — absent. ~634 params missing.

#### Format A Limitations

- Covers only 761 of ~1395 params (55%)
- Delay Time, many frequency params, some bipolar params are absent
- `block_idx` field is mostly 0 (cannot identify which block a record belongs to)
- Block identification relies on param_id sequence matching against all_params.json

### Block-Based Structure (experimental) — ⚠️ PARTIALLY VERIFIED

A second interpretation of the cache data, using 8-byte block headers (`u32 block_id`,
`u32 num_params`) followed by parameter records. 39 block headers detected.

**Status: ⚠️ PARTIALLY VERIFIED** — Only AMP (cache_id=10) confirmed. DRIVE mapping
FAILED verification. The relationship between this structure and Format A is unclear.
They may be two views of the same data, or genuinely separate sections.

#### What's confirmed:
- 39 positions match the block header pattern (preceded by enum trailer or zeros)
- AMP block (cache_id=10): continuous params at idx=11-15 have max=10.0, matching
  hand-verified Gain/Bass/Mid/Treble/Master — ✅
- Enum records contain valid ASCII strings (effect type names, tempo values, etc.)
- Enum trailer pattern: `[XX] 80 00 00 00 00` (byte[1]=0x80 is the marker)

#### What's NOT confirmed:
- Whether `param_index` in block-based records equals SysEx `param_id` (FAILED for DRIVE)
- Whether block-based max values are "normalized" or simply wrong due to misalignment
- Mapping of cache block_id to SysEx block_id (only AMP confirmed)
- Whether the block-based structure and Format A are independent or overlapping

#### Observed max value behavior (AMP only):
- `continuous` params (Gain, Bass, etc.): max matches display max (10.0) ✓
- `frequency` params: max = 1.0 (normalized, actual Hz value not stored here)
- `bipolar` params: max = 1.0 or 100.0 (relationship to display range unclear)

### Dual-Format Strategy (TODO)

**Recommended approach**: Use Format A as the primary source for max/min values
(since these are confirmed accurate). Use block-based structure only for:
- Type classification (flags are reliable)
- Enum value lists (string data is valid)
- Coverage of params missing from Format A (with caution — values unverified)

#### Next Steps

1. Write a new `apply_format_a.py` script that:
   - Uses Format A's param_id + sequence order to match against all_params.json
   - Applies max/min/step only where Format A values are available
   - `--dry-run` mode with diff output
   - Never overwrites `verified: true` params
2. Validate the script output against hand-verified AMP/Drive params
3. Investigate why ~634 params are missing from Format A (different encoding? different section?)

### Known Issues

- **`apply_cache_to_all_params.py` is BROKEN** — block-matching logic has bugs.
  DO NOT RUN. Will corrupt all_params.json.
- **Block-based `param_index` ≠ SysEx `param_id`**: Confirmed failure for DRIVE.
  The block-based sequential index does not reliably correspond to SysEx param_id.
- **Format A `block_idx` is useless**: Almost always 0. Cannot identify blocks.
- **Enum trailer byte[0] is variable**: Pattern is `[XX] 80 00 00 00 00`.
  Detection must check byte[1]==0x80 only.
- **Large enums (>500 values)**: CABINET block has 1024-entry IR name enums.
  After large enums, padding (`ff 00 00 00` repeated) fills unused slots.
- **GAPs between blocks**: Contain catalog data (preset names, cab IR names,
  tempo value lists) — NOT additional parameter definitions.

## FM9-Edit Binary Analysis

**FM9-Edit is a native JUCE (C++) application**, NOT Electron. The binary is a
Mach-O universal (x86_64 + arm64). No asar/JS extraction possible.

### Embedded ZIP Resources

Two identical ZIP archives are embedded in the binary (one per architecture slice).
They contain UI layout XMLs, fonts, images, and SVGs.

**Extraction** (from universal binary, no `lipo` needed):
```python
import zipfile, io
with open('/Applications/FM9-Edit.app/Contents/MacOS/FM9-Edit', 'rb') as f:
    data = f.read()
# First archive at ~0x00dce3b8 (find PK\x03\x04 for __components.xml)
# EOCD at ~0x00df1c03
zf = zipfile.ZipFile(io.BytesIO(data[0x00dce3b8:0x00df1c19]))
block_layout = zf.read('__block_layout.xml')  # 1,161,708 bytes
```

**Key files in ZIP:**
| File | Size | Content |
|------|------|---------|
| `__block_layout.xml` | 1.16 MB | UI widget layout for all effect pages. Maps `parameterName` (e.g., `DELAY_TIME`) to UI controls. Contains `knobDirection="bipolar"` hints. |
| `__amp_layout.xml` | 213 KB | Amp-specific layout (type variants) |
| `__amp_layout_v06p00.xml` | 220 KB | Amp layout (older firmware compat) |
| `__components.xml` | 418 KB | Skin/theme definitions |

**Note**: These XMLs define UI layout only. They do NOT contain min/max/step values.
Parameter ranges come from the effectDefinitions cache (queried from firmware at runtime).

### Parameter Name Table in Binary

The binary contains null-terminated parameter name strings in enum order:
```
DELAY_MODEL, DELAY_TYPE, DELAY_TIME, DELAY_RATIO, DELAY_FEED, ...
```
88 DELAY params, 143 DISTORT (Amp) params, etc. — same data as Ghidra extraction.

### Command Name Table

At ~0x005b1952, a table of SysEx command names used by FM9-Edit:
```
begin communications, complete communications, loop_start, loop_end,
query_device_model, query_device_version, query_device_name, query_sys_info,
block_lib_read, get_param_info_all, get_param_info, get_patch_names,
get_user_cabinets, get_scratch_cabinets, effects_pool, patch_save,
patch_change, patch_revert, patch_clear, patch_name, scene_change, ...
```
69+ commands identified. `get_param_info_all` and `get_param_info` correspond to
SysEx func 0x17 (confirmed via live test — FM9 responds with ACK).

## Key Files (runtime data)

All in `data/fm9/` (committed to git):

| File | Records | Source | Description |
|------|---------|--------|-------------|
| `all_params.json` | 37 blocks × ~1395 params | Ghidra + cache + calibration | param_id, name, type, min, max, decode_max, decode_style |
| `amp_types.json` | 396 models | Live scan | Amp model enum (type_id → name) |
| `drive_types.json` | 86 models | Live scan | Drive model enum (type_id → name) |
| `effect_definitions.json` | All types | Cache strings | Model/type name lists |
| `type_valid_params.json` | Amp 331 types | XML | Type-specific valid params |
| `wiki_models.json` | Amp + Drive | Wiki scrape | "Based on" info |
| `wiki_blocks.json` | All blocks | Wiki scrape | Block descriptions |

Test artifacts in `tests/`:

| File | Description |
|------|-------------|
| `calibrate_decode.py` | GET decode calibration script (measures decode_max per param) |
| `test_roundtrip.py` | Automated SET→GET verification |
| `classify_failures.py` | Categorize roundtrip failures into actionable groups |
| `fix_from_failures.py` | Auto-fix all_params.json from failure patterns (schema v1, needs update) |
| `probe_blocks.py` | Block liveness probe (identifies firmware-crashing blocks) |
| `calibration_results.json` | Raw calibration measurement data |
| `roundtrip_results.json` | Latest roundtrip test results |
