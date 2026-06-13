# FM9 USB MIDI SysEx Protocol Reference

Reverse-engineered from FM9 Editor ↔ FM9 communication via Wireshark USB captures.
Applies to FM9 (model_id=0x12), Axe-Fx III (0x10), and FM3 (0x11).

## Message Format

```
F0 00 01 74 [model_id] [func] [payload...] [checksum] F7
```

| Field | Bytes | Description |
|-------|-------|-------------|
| F0 | 1 | SysEx start |
| 00 01 74 | 3 | Fractal Audio manufacturer ID |
| model_id | 1 | 0x12=FM9, 0x10=Axe-Fx III, 0x11=FM3 |
| func | 1 | Function code |
| payload | variable | Function-specific data |
| checksum | 1 | See below |
| F7 | 1 | SysEx end |

### Checksum

```python
checksum = model_id
for byte in [func] + payload:
    checksum ^= byte
checksum = (checksum ^ 0x05) & 0x7F
```

## Function Codes

### Simple Commands (PC → FM9)

| func | Name | Payload | Description |
|------|------|---------|-------------|
| 0x08 | FIRMWARE_INFO | (none) | Query firmware version |
| 0x0A | SET_BYPASS | id_lo, id_hi, dd | Set block bypass state |
| 0x0C | SET_SCENE | scene | Switch scene (0-7) |
| 0x0D | GET_PRESET_NAME | lo, hi | Get preset name / current preset (see below) |
| 0x13 | STATUS_DUMP | (none) | Query all block states |
| 0x17 | GET_PARAM_INFO | block_id, param_id(?) | Query parameter definition (see below) |
| 0x1F | GET_BLOCK | block_id, 0x00 | Request block data |
| 0x47 | DEVICE_INFO | (none) | Query device configuration |

### Block Data Transfer (bidirectional)

| func | Name | Description |
|------|------|-------------|
| 0x74 | BLOCK_SELECT | Block header (precedes data chunks) |
| 0x75 | PRESET_DATA | Data chunk (776 bytes typical) |
| 0x76 | COMMIT | Confirms write operation |

### Multipurpose Message (func=0x01)

Most Editor ↔ FM9 communication uses func=0x01 with sub-function codes:

```
F0 00 01 74 [model] 01 [sub] [page] [block_id] [p0 p1 p2] [d0..d8] [cs] F7
                                                  (3 bytes)   (9 bytes)
Total: 23 bytes (standard) or 26 bytes (extended, sub=0x35)
```

| Sub | Direction | Name | Description |
|-----|-----------|------|-------------|
| 0x01 | both | BLOCK_STATUS | Bypass/channel state (115-byte response) |
| 0x09 | OUT | SET_PARAM | Set parameter value (with channel encoding) |
| 0x16 | OUT | SET_CHANNEL | Switch block channel (A/B/C/D) |
| 0x1A | IN | PARAM_NOTIFY | Parameter value broadcast (device → host) |
| 0x1B | IN | PARAM_META | Parameter metadata broadcast |
| 0x26 | OUT | STORE_PRESET | Save preset to flash |
| 0x27 | OUT | CHANGE_PRESET | Switch to different preset |
| 0x28 | OUT | SET_PRESET_NAME | Rename preset (60 bytes, 7-bit packed name) |
| 0x2A | OUT | QUERY_PRESET_NAME | Get preset name by number |
| 0x2B | OUT | SET_SCENE_NAME | Set scene name (60 bytes, 7-bit packed) |
| 0x2E | both | GRID_QUERY | Read grid layout (753-byte response) |
| 0x30 | OUT | LAYOUT_BEGIN | Start grid operation (block add/delete/move) |
| 0x32 | OUT | BLOCK_ADD | Add block at grid position |
| 0x33 | OUT | BLOCK_DELETE | Delete block at grid position |
| 0x35 | OUT | CABLE_OP | Connect/disconnect cable (26 bytes) |
| 0x36 | OUT | BLOCK_MOVE | Move block in direction |
| 0x37 | both | TIMING_SYNC | Heartbeat/timing |
| 0x52 | OUT | SLIDE_PARAM | Set parameter value (no Undo, for real-time drag) |
| 0x7B | both | HEARTBEAT | Keep-alive polling |

## SET_BYPASS (func=0x0A)

```
F0 00 01 74 [model] 0A [id_lo] [id_hi] [dd] [cs] F7
```

- id = effect_id (14-bit: id_lo | id_hi << 7)
- dd = 0 (engaged/ON), 1 (bypassed/OFF)

## SET_SCENE (func=0x0C)

```
F0 00 01 74 [model] 0C [scene] [cs] F7
```

- scene: 0x00=Scene 1, 0x01=Scene 2, ..., 0x07=Scene 8

## GET_PRESET_NAME (func=0x0D)

Query preset name by number, or query the current preset.

### Query Preset Name by Number

```
Request:  F0 00 01 74 [model] 0D [preset_lo] [preset_hi] [cs] F7
Response: F0 00 01 74 [model] 0D [preset_lo] [preset_hi] [name × 32] [0x00] [cs] F7
```

Returns the specified preset's number (echoed) and name.
Name is **plain ASCII** (not 7-bit packed), 32 bytes, space-padded.

### Query Current Preset (magic value 0x7F, 0x7F)

```
Request:  F0 00 01 74 [model] 0D 7F 7F [cs] F7
Response: F0 00 01 74 [model] 0D [preset_lo] [preset_hi] [name × 32] [0x00] [cs] F7
```

Sending the invalid preset number 0x7F,0x7F (16383) causes the FM9 to return
the **current** preset number and name in a single response.

> **Note**: The no-argument form (`F0 00 01 74 [model] 0D [cs] F7`) returns
> all zeros on FM9 firmware and does NOT reliably return the current preset number.
> Always use the 0x7F,0x7F magic value instead.

### Usage

```python
# Get current preset number and name (single query)
send([0x0D, 0x7F, 0x7F, checksum])
# Response byte[5] = preset_lo, byte[6] = preset_hi
preset_number = response[5] | (response[6] << 7)
# Response byte[7:39] = name (32 bytes ASCII)
name = ''.join(chr(b) for b in response[7:39] if 32 <= b < 127).rstrip()
```

## STATUS_DUMP (func=0x13)

Request: `F0 00 01 74 [model] 13 [cs] F7`

Response contains 3-byte packets for each active block:
```
[id_lo] [id_hi] [dd]
```
- effect_id = id_lo | (id_hi << 7)
- dd bit 0 = bypass state
- dd bits 1-3 = channel (0=A, 1=B, 2=C, 3=D)

## GET_PARAM_INFO (func=0x17) — Partially Reverse-Engineered

Queries parameter definitions (min/max/step/type) from firmware.
FM9-Edit uses this at startup to build the effectDefinitions cache.

### Discovery

- Command names `get_param_info_all` and `get_param_info` found in FM9-Edit binary
- FM9 responds with ACK (func=0x64, sub=0x17) confirming the function exists
- FM9-Edit's "Query All Param Definitions" UI string references this function

### Observed Behavior

```
Request:  F0 00 01 74 12 17 [payload] [cs] F7
Response: F0 00 01 74 12 64 17 [status] [cs] F7  (ACK)
```

Status codes observed:
- `0x00` = success
- `0x01` = error (invalid request)
- `0x05` = error (invalid length / missing payload)

### Unknown

- Correct payload format (block_id encoding, param_id encoding)
- Response data format (how min/max/step/type are returned)
- Whether `get_param_info_all` uses a different payload than `get_param_info`

### Significance

If fully decoded, this would allow querying parameter definitions directly from
firmware without relying on the effectDefinitions cache file. This would enable
runtime discovery of new parameters after firmware updates.

## GET_BLOCK (func=0x1F)

Request: `F0 00 01 74 [model] 1F [block_id] 00 [cs] F7`

Response sequence:
1. func 0x74 — Block select header (variable length, block-specific)
2. func 0x75 × N — Data chunks (776 bytes each, N varies by block type)
3. func 0x76 — Commit confirmation

### Chunk Structure

Each chunk (func 0x75):
- bytes[0:7] = header (00 01 74 [model] 75 [seq] [chunk_count])
- bytes[7:-1] = parameter data (3 bytes per parameter)
- bytes[-1] = checksum

Parameter at index N: `offset = 7 + N * 3`

### Block Data Channel Layout

All 4 channels (A/B/C/D) are stored contiguously in the block data returned by GET_BLOCK.
Multiple SysEx chunks (func 0x75) are concatenated — strip the 7-byte header **and the
last byte (checksum)** from each chunk to form one continuous buffer.

```python
# Correct concatenation (confirmed 2026-06-13):
combined = chunks[0][:-1]            # first chunk: strip checksum only
for c in chunks[1:]:
    combined += c[7:-1]              # subsequent: strip header + checksum

# Channel stride
channel_stride = (len(combined) - 7) // 4
# Channel N starts at offset: 7 + N * stride
```

> **Critical**: Each chunk ends with a checksum byte that is NOT parameter data.
> Failing to strip it causes a cumulative 1-byte-per-chunk offset error that
> corrupts Channel B/C/D reads (Channel A is unaffected as it fits within chunk 0).

| Channel | N | Offset |
|---------|---|--------|
| A | 0 | 7 |
| B | 1 | 7 + stride |
| C | 2 | 7 + 2×stride |
| D | 3 | 7 + 3×stride |

Within each channel's region, parameters are packed at 3 bytes each (same layout as the
single-channel case). The active channel is determined by querying STATUS_DUMP (func 0x13)
or by using SET_CHANNEL (sub=0x16) to switch before reading/writing.

### Parameter Decode Rules (GET_BLOCK → display value) — CONFIRMED 2026-06-04

Raw values are 21-bit (3 × 7-bit MIDI bytes): `raw = lo | (hi << 7) | (msb << 14)`.

**Six distinct decode patterns exist.** The pattern is determined by:
1. Cache `flags` field (static, identifies 4096-scale params)
2. `decode_style` (measured via calibration: SET 0 → read raw → center or zero?)
3. `decode_max` (measured via calibration: SET known value → read raw → compute)
4. Parameter `type` classification (switch, enum, signed_int, frequency, bipolar, continuous)

#### Pattern 1: 4096 Scale (Fixed-Point)

**Identification**: `cache_flags == 0x0430` (exactly 4 parameters in entire firmware)

```
display = (raw + 4) / 4096 * display_max
```

Internal raw range is 0–4092 (12 bits). Upper bits unused.
FM9 encodes as: `raw = round(normalized * 4096 - 4)`, clamp to 0.

| Parameter | Block | display_max | Verified |
|-----------|-------|-------------|----------|
| Time (pid=12) | Delay | 1000 ms | ✅ |
| Timer (pid=30) | Delay | 1000 ms | ✅ |
| Time (pid=2) | Megatap/Plex (cid=33) | 1000 ms | — |
| Time (pid=4) | Megatap/Plex (cid=33) | 1000 ms | — |

Verified data points (Delay 1 Time, display_max=1000):

| SET | raw | (raw+4)/4096×1000 |
|-----|-----|-------------------|
| 10 | 37 | 10.01 ✅ |
| 100 | 406 | 100.10 ✅ |
| 250 | 1020 | 250.00 ✅ |
| 500 | 2044 | 500.00 ✅ |
| 1000 | 4092 | 1000.00 ✅ |

Note: The legacy calibration approach (`decode_max=16030.82` with `raw/65534*decode_max`)
is a linear approximation that introduces ~0.1–1.0 ms error depending on value.

#### Pattern 2: 65534 Linear, Center Bipolar

**Identification**: `decode_style == "center"` (calibration: SET 0 → raw ≈ 32767)

```
display = (raw - 32767) / 32767 * decode_max
```

Range: raw=0 → -decode_max, raw=32767 → 0, raw=65534 → +decode_max.

| Example | display_max (cache) | decode_max (actual) | ratio |
|---------|--------------------|--------------------|-------|
| Feed ±100% | 100 | 100 | 1.0 |
| Gain1 ±12 dB | 1.0 | 12.0 | 12.0 |
| Spread ±1.0 | 1.0 | 2.0 | 2.0 |

Verified: Feed pid=14, raw_float=-0.5 → raw=16384 → `(16384-32767)/32767*100 = -50.00` ✅
Verified: Gain1 pid=69, raw_float=0.5 → raw=34132 → `(34132-32767)/32767*12 = 0.50 dB` ✅

#### Pattern 3: 65534 Linear, Zero-Based Bipolar

**Identification**: `decode_style == "zero"` AND `type == "bipolar"`
(calibration: SET 0 → raw ≈ 0, but parameter has negative display range)

```
display = raw / 65534 * decode_max + param_min
```

Where `decode_max` = total range (max − min), stored in all_params.json.

Range: raw=0 → param_min, raw=32767 → center (0), raw=65534 → param_max.

| Example | display range | decode_max | param_min |
|---------|--------------|------------|-----------|
| Mstrfdbk ±100% | -100..+100 | 200 | -100 |
| Mstrtime ±100% | -100..+100 | 200 | -100 |

**Important**: `decode_max` for zero-bipolar is the **total range** (max - min = 200),
NOT the positive half (100). The calibration script computes it as
`pmax * 65534 / raw_at_max` where raw_at_max is the raw value when SET 1.0 is sent.

**SET limitation**: Normalized encoding (sub=0x09) only reaches the positive half
of the raw range (raw 0..32767 for normalized 0..1.0). Negative display values
require GET→MODIFY→PUT (write raw bytes directly). This matches FM9-Edit behavior.

#### Pattern 4: 65534 Linear, Continuous (Zero-Based)

**Identification**: default for `type == "continuous"` (calibration: SET 0 → raw ≈ 0)

```
display = raw / 65534 * decode_max
```

Range: raw=0 → 0, raw=65534 → decode_max.

Most common pattern. `decode_max` often equals `display_max` but NOT always:

| Example | display_max | decode_max | ratio | Reason |
|---------|------------|------------|-------|--------|
| Mix 0–100% | 100 | 100 | 1.0 | Standard |
| Splicetime | 1000 | 500 | 0.5 | Actual range is 500ms |
| LFO Phase | 57.2958 (1 rad) | 180 (π rad) | π | Internal = degrees |
| Bypass (Delay) | 10 | 15 | 1.5 | Internal headroom |
| Q (Delay) | 10 | 25.13 | 2.513 | Internal Q range |

#### Pattern 5: Frequency (Logarithmic Scale)

**Identification**: `type == "frequency"` AND `display_max >= 2000` (typically 20000 Hz)

```
display = min_freq * 10^(raw / 65534 * log₁₀(decode_max / min_freq))
```

Where `min_freq = max(param_min, 20.0)` (typically 20 Hz).

| Example | min_freq | display_max (cache) | decode_max (actual) | ratio |
|---------|----------|--------------------|--------------------|-------|
| PEQ Freq1 | 20 Hz | 20000 Hz | 2000 Hz | 0.1 |

**Critical**: `decode_max` for frequency params is the **actual maximum frequency**,
which differs from the cache `display_max`. The FM9 receives Hz via raw_float and
applies log₁₀ transformation internally for storage.

Verified: PEQ Freq1, SET raw_float=100 Hz → raw=22903 →
`20 * 10^(22903/65534 * log₁₀(2000/20))` = 100.0 Hz ✅

**SET encoding** for frequency params: `raw_float=True` with Hz value directly.
FM9 applies the log transform internally.

**Note**: Not all "frequency" type params in the cache are true log-scale. LFO Phase
(cache flags=frequency due to bit 9) uses linear Pattern 4 despite being classified
as frequency in the cache. The distinguishing factor is `display_max`:
- `display_max >= 2000`: true log-scale (Pattern 5)
- `display_max < 100`: linear (Pattern 4 with different decode_max)

#### Pattern 6: Signed Integer (Two's Complement)

**Identification**: `type == "signed_int"` (e.g., Pitch Shift semitones)

```
display = raw                    (if raw ≤ 32767)
display = raw - 65536            (if raw > 32767)
```

Range: ±24 semitones for Pitch block Virtual Capo.
SET: `raw_float=True` with semitone value directly (e.g., -1.0 for down 1 semitone).

#### Switch and Enum (trivial)

```
switch: display = bool(lo)           (lo != 0 → True)
enum:   display = raw_val            (integer index, 0-based)
```

#### Cache Flags → 4096 Scale Identification

The effectDefinitions cache stores a 16-bit `flags` field per parameter record.
**Only `flags == 0x0430`** indicates 4096-scale storage. All other flag values use
65534 scale (with varying decode_max determined by calibration).

```
0x0430 = 0000_0100_0011_0000  → 4096 scale (4 params total)
0x0431 = 0000_0100_0011_0001  → 65534 scale (ms-range continuous)
0x0432 = 0000_0100_0011_0010  → 65534 scale (fine-resolution ms)
0x0433 = 0000_0100_0011_0011  → 65534 scale (ultra-fine ms)
0x0441–0x0443                  → 65534 scale (auto-step ms)
```

Key bit interpretation:
- bit 0: distinguishes 4096 (0) from 65534 (1) within the 0x043x group
- bit 8 (0x0100): bipolar flag
- bit 9 (0x0200): frequency flag (log-scale if display_max ≥ 2000)
- bit 10 (0x0400): time/period semantic flag

#### decode_max Determination Strategy

`decode_max` CANNOT be derived from the cache alone — live calibration is required.
The calibration process (per parameter):

1. SET 0 (or min_freq for frequency) → read raw → determines `decode_style`
   - raw ≈ 0: zero-based
   - raw ≈ 32767: center bipolar
2. SET 50% of display_max → read raw → compute `decode_max`
   - zero-based: `decode_max = test_val * 65534 / raw`
   - center: `decode_max = test_val * 32767 / (raw - 32767)`
   - frequency: solve log equation for decode_max

Run `tests/calibrate_decode.py --all --apply` to calibrate all blocks (~5 min with FM9 connected).

## SET_TYPE / SET_PARAM (sub=0x09) / SLIDE_PARAM (sub=0x52)

Change amp/drive model, cab IR, or set any parameter value.
sub=0x09 and sub=0x52 share the same message format. The difference is behavioral:
- **sub=0x09**: Value set (recorded in Undo history)
- **sub=0x52**: Slide/drag (not recorded in Undo history, for real-time continuous control)

```
F0 00 01 74 [model] 01 [sub] 00 [block_lo] [block_hi] [param_lo] [param_hi] [d0 d1 d2 d3 d4] 00 00 [ch] 00 [cs] F7
```

### Channel Encoding (Axe-Fx III)

The byte at position [14] (after func) specifies the target channel:

| Channel | Value | Formula |
|---------|-------|---------|
| A | 0x00 | channel × 0x20 |
| B | 0x20 | channel × 0x20 |
| C | 0x40 | channel × 0x20 |
| D | 0x60 | channel × 0x20 |

> **Important (FM9 behavior)**: In practice, the channel byte in SET_PARAM is always 0x00.
> FM9 Edit does NOT use this byte to target a specific channel. Instead, it switches the
> active channel first via SET_CHANNEL (sub=0x16), then sends SET_PARAM with channel=0x00.
> The channel byte encoding above is from Axe-Fx III documentation but is not used on FM9.

> **Important**: Parameter IDs (param field) differ between Axe-Fx III and FM9, even for the same block type and model variant. Each device requires its own parameter scan. The channel encoding and message structure are identical across devices.

### For Enum Parameters (Amp Type, Drive Type)

| block_id | param | Purpose |
|----------|-------|---------|
| 0x3A (Amp) | 0x0A | Amp model type |
| 0x76 (Drive) | 0x0A | Drive model type |

Type ID is 21-bit packed into d[2:5]: `d[2] | (d[3] << 7) | (d[4] << 14)`
(d[0] and d[1] are zero for enum parameters)

### For Cab IR Selection

Cab IR selection uses **raw float encoding** (same as continuous params), NOT the enum format above.
Two parameters must be set in sequence:

| Step | Param | Value (raw float) | Description |
|------|-------|-------------------|-------------|
| 1 | 0 (slot 1) or 1 (slot 2) | Bank number | 0=Factory 1, 1=Factory 2, 2=User, 3=Legacy |
| 2 | 4 (slot 1) or 5 (slot 2) | IR index | 0-based index within the selected bank |

Cab Mode (param 31): 0=IR mode, 1=DynaCab mode. Must be set to 0 for IR selection to take effect.

DynaCab parameters (when Mode=1) — all use raw float encoding:
| Param | Description | Values |
|-------|-------------|--------|
| 85 | DynaCab Type slot 1 | Cabinet index (raw float) |
| 86 | DynaCab Type slot 2 | Cabinet index (raw float) |
| 89 | DynaCab Mic slot 1 | 0=Condenser, 1=Ribbon, 2=Dynamic 1, 3=Dynamic 2 |
| 90 | DynaCab Mic slot 2 | 0=Condenser, 1=Ribbon, 2=Dynamic 1, 3=Dynamic 2 |
| 93-96 | DynaCab R1-R4 (position) | **Normalized 0.0–1.0** (exception to raw float rule) |
| 97-99, 104 | DynaCab Z1-Z4 (distance) | **Normalized 0.0–1.0** (exception to raw float rule) |

Mute parameters (raw float 0=unmuted, 1=muted):
| Param | Description |
|-------|-------------|
| 24 | Mute slot 1 |
| 25 | Mute slot 2 |
| 26 | Mute slot 3 |
| 27 | Mute slot 4 |

> **Note**: Most Cab parameters use raw float encoding (actual values as IEEE 754 float),
> unlike Amp/Drive which use normalized 0.0–1.0. The exceptions are DynaCab R/Z (position/distance)
> which use normalized 0.0–1.0.

### For Continuous Parameters (Gain, Bass, Mid, etc.)

Value is **IEEE 754 32-bit float** (normalized 0.0-1.0) packed into 5 x 7-bit bytes.
Both `block_id` and `param` fields use 2-byte 7-bit encoding: `[value & 0x7F, (value >> 7) & 0x7F]`.

```
F0 00 01 74 [model] 01 [sub] 00 [block_lo] [block_hi] [param_lo] [param_hi] [d0 d1 d2 d3 d4] 00 00 [ch] 00 [cs] F7
```

Example param_ids (FM9 Amp 1):

| param_id | Parameter |
|----------|-----------|
| 11 (0x0B) | Gain |
| 12 (0x0C) | Bass |
| 13 (0x0D) | Mid |
| 14 (0x0E) | Treble |
| 15 (0x0F) | Master Volume |
| 30 (0x1E) | Presence (P.A.) |
| 137 (0x89) | Preamp Presence |

> **Note**: param_id > 127 requires 2-byte encoding. E.g., param_id=137: lo=0x09, hi=0x01.

Value is **IEEE 754 32-bit float** (normalized 0.0-1.0) packed into 5 x 7-bit bytes:

```python
import struct

def encode_param_value(display_value, display_max):
    """Encode parameter value for sub=0x09."""
    normalized = display_value / display_max  # 0.0 to 1.0
    raw32 = struct.unpack('I', struct.pack('f', normalized))[0]
    return [
        raw32 & 0x7F,
        (raw32 >> 7) & 0x7F,
        (raw32 >> 14) & 0x7F,
        (raw32 >> 21) & 0x7F,
        (raw32 >> 28) & 0x7F,
    ]
```

Example: Gain=5.0 (max=10.0) → normalized=0.5 → IEEE 754=0x3F000000 → `[0x00, 0x00, 0x00, 0x78, 0x03]`

## SET_CHANNEL (sub=0x16)

```
F0 00 01 74 [model] 01 16 00 [block_id] 00 00 00 [channel] 00 00 00 00 00 00 00 00 [cs] F7
```

- channel: 0x00=A, 0x01=B, 0x02=C, 0x03=D

## Grid Operations

### Grid Position Encoding

```python
grid_position = col * 6 + row  # col: 0-13, row: 0-4
```

### BLOCK_ADD (sub=0x30 + sub=0x32)

```
Step 1 (sub=0x30): block_id=0x00, p=[00,00,00], d[0]=grid_position
Step 2 (sub=0x32): payload=[01,32,00,id_lo,id_hi,00,00,grid_pos,00...00,cs]
```

Block ID encoding (supports >0x7F):
```python
id_lo = block_id & 0x7F
id_hi = (block_id >> 7) & 0x7F
# e.g., Gate (0x92=146): id_lo=0x12, id_hi=0x01
```

### SHUNT_ADD (sub=0x30 + sub=0x32)

Shunts are cable pass-through placeholders. They use the same sub=0x30/0x32 pair
as block add, but with a **sequential shunt index** in byte[3]:

```
Step 1 (sub=0x30): block_id=0x00, p=[00,00,00], d[0]=grid_position
Step 2 (sub=0x32): payload=[01,32,00,shunt_index,08,00,00,grid_pos,00...00,cs]
```

- `byte[3]` = shunt_index (0, 1, 2, 3, ... — must be unique per preset)
- `byte[4]` = 0x08 (shunt type flag)

**Critical**: Each shunt in a preset must have a unique index. When adding multiple
shunts, increment the index for each one. Query the grid first to find the current
maximum shunt index, then start from max + 1.

### BLOCK_DELETE (sub=0x30 + sub=0x33)

```
Step 1 (sub=0x30): d[0]=grid_position
Step 2 (sub=0x33): d[0]=grid_position
```

### BLOCK_MOVE (sub=0x30 + sub=0x36)

```
Step 1 (sub=0x30): d[0]=source_grid_position
Step 2 (sub=0x36 × N): d[0]=direction, repeated N times
```

Direction codes:
| d[0] | Direction | Scope |
|------|-----------|-------|
| 0x00 | ← Left | Single block |
| 0x01 | → Right | Single block |
| 0x02 | ↑ Up | Single block |
| 0x03 | ↓ Down | Single block |
| 0x04 | ← Left | Entire column |
| 0x05 | → Right | Entire column |
| 0x06 | ↑ Up | Entire row |
| 0x07 | ↓ Down | Entire row |

### CABLE_OP (sub=0x35, 26 bytes)

```
F0 00 01 74 [model] 01 35 00 00 00 00 00 [op] 00 00 00 00 00 00 02 00 [d9] [d10] [d11] 00 00 [cs] F7
```

- op: 0x01=connect, 0x02=disconnect
- d9/d10/d11: encoded source and destination grid positions

```python
def encode_cable_coords(from_row, from_col, to_row, to_col):
    from_pos = from_col * 6 + from_row
    to_pos = to_col * 6 + to_row
    d9 = from_pos >> 1
    d10 = (to_pos >> 2) | ((from_pos & 0x01) << 6)
    d11 = (to_pos & 0x03) << 5
    return d9, d10, d11
```

## Grid Layout Query (sub=0x2E)

### Request

```
F0 00 01 74 [model] 01 2E 00 00 00 00 00 00 00 00 00 00 00 00 00 00 [cs] F7
```

### Response (753 bytes)

Grid region starts at byte offset 361 (mido data). Size: 392 bytes = 14 columns × 28 bytes.

The data is a continuous 7-bit bitstream. Each cell = 32 bits:

```
cell_start_bit = 46 + col * 192 + row * 32
```

### Cell Structure (32 bits)

| Bits | Field | Description |
|------|-------|-------------|
| 0-7 | block_id << 1 | 7-bit block ID shifted left (LSB unused) |
| 8-15 | block_type | 0x08=shunt, 0x00=real block |
| 16-23 | cable_input | Bitmask: bit N+1 = cable from row N |
| 24-31 | reserved | Always 0x00 |

### Reading 8 bits from 7-bit stream

```python
def read_8bits(data, bit_offset):
    byte_idx = bit_offset // 7
    bit_within = bit_offset % 7
    available = 7 - bit_within
    first = data[byte_idx] & ((1 << available) - 1)
    needed = 8 - available
    second = (data[byte_idx + 1] >> (7 - needed)) & ((1 << needed) - 1)
    return (first << needed) | second
```

## Preset Name Encoding

7-bit bitstream packing of ASCII characters:

```python
def encode_name(name, max_len=32):
    name = name.ljust(max_len, ' ')[:max_len]
    bits = ''.join(f'{ord(c):08b}' for c in name)
    return [int(bits[i:i+7].ljust(7,'0'), 2) for i in range(0, len(bits), 7)]

def decode_name(data):
    bits = ''.join(f'{b:07b}' for b in data)
    return ''.join(chr(int(bits[i:i+8], 2)) for i in range(0, len(bits)-7, 8)
                   if int(bits[i:i+8], 2) > 0).rstrip()
```

## SET_SCENE_NAME (sub=0x2B)

Same structure as SET_PRESET_NAME but sets a scene name instead.

```
F0 00 01 74 [model] 01 2B 00 00 00 [scene_index] 00 00 00 00 00 00 00 00 20 00 [name_37bytes] [cs] F7
```

- scene_index: 0x00=Scene 1, 0x01=Scene 2, ..., 0x07=Scene 8
- name: 7-bit packed encoding (same as preset name), max 32 ASCII characters
- Total message: 60 bytes (same as SET_PRESET_NAME)

Confirmed via Wireshark capture (2026-05-27).

## Block-Specific Parameter Encoding

Different blocks use different encoding for SET_PARAM (sub=0x09).

**Key discovery (2026-05-29):** All effect blocks use **unified normalized encoding**
(value/max → 0.0-1.0) for SET. The FM9 interprets the normalized value based on
the parameter's internal type. GET (func=0x1F) uses a different max value (internal
storage max) which must be calibrated via roundtrip measurement.

### SET Encoding (sub=0x09) — Confirmed 2026-05-29

**All effect blocks** (Delay, Reverb, Chorus, PEQ, Comp, Flanger, Phaser, Pitch, Wah, GEQ, etc.):

| Parameter type | Encoding | Formula | Example |
|---|---|---|---|
| Continuous | normalized 0.0–1.0 | `value / display_max` | Time=350ms, max=1000 → 0.35 |
| Bipolar | normalized ±1.0 | `value / display_max` | Feed=20%, max=100 → 0.2 |
| Switch | raw_float | `0.0` or `1.0` | — |
| Enum | raw_float | integer index as float | Type=3 → 3.0 |
| Signed int | raw_float | semitone value | Shift=-2 → -2.0 |

FM9 interprets bipolar normalized values as: 0.0=center, +1.0=positive max, -1.0=negative max.

### Amp / Drive (block 0x3A, 0x76)
- Continuous params (Gain, Bass, Mid, Treble, etc.): **Normalized 0.0–1.0** (value / max) — via dedicated tools only
- Bipolar params (Level, Balance): **Raw float** (display value as IEEE 754, e.g., -10.0 for -10 dB). NOT normalized.
  - Level range: -80 to +20 dB (most blocks). Compressor: -20 to +20 dB. Amp Out Comp Threshold: -60 to 0 dB.
- Frequency params (High Cut, Low Cut, Mid Frequency, etc.): **UNRESOLVED** —
  Normalized encoding has no effect on FM9 (raw stays at 0). Raw float with Hz
  value partially works but decode_max is unconfirmed. Needs dedicated calibration.
  See "Known Issues" below.
- Type selection: Uses dedicated `fm9_set_amp_type` / `fm9_set_drive_type` tools

### Cab (block 0x3E–0x41)
- Mode, DynaCab Type, DynaCab Mic: **Raw float** (integer as IEEE 754, e.g., 31.0 for Type index 31)
- Frequency params (High Cut, Low Cut): **Raw float** (Hz value directly)
- DynaCab R/Z (position/distance): **Normalized 0.0–1.0** (only Cab params that use normalized)
- All other params: **Raw float**

### GET Decode (func=0x1F) — CONFIRMED 2026-06-04

See "Parameter Decode Rules" section above for the complete 6-pattern decode algorithm.

Summary table:

| Pattern | Condition | Formula |
|---|---|---|
| 4096 scale | `cache_flags == 0x0430` | `(raw + 4) / 4096 * display_max` |
| center bipolar | `decode_style == "center"` | `(raw - 32767) / 32767 * decode_max` |
| zero bipolar | `decode_style == "zero"` + bipolar | `raw / 65534 * decode_max - decode_max/2` |
| continuous | default | `raw / 65534 * decode_max` |
| frequency (log) | `type == "frequency"` + max≥2000 | `min * 10^(raw/65534 * log₁₀(decode_max/min))` |
| signed_int | `type == "signed_int"` | `raw if raw≤32767 else raw-65536` |

**Critical**: `decode_max` often differs from `display_max` and MUST be measured
via live calibration (`tests/calibrate_decode.py`). Cannot be derived from cache alone.

Known decode_max/display_max ratios:
- π (3.14): LFO Phase (rad↔deg conversion)
- 12: Parametric EQ gain (±12 dB range)
- 2: zero-bipolar total range
- 0.5: actual max is half of cache max (clamped params)
- 0.1: frequency decode_max (log scale internal range)

Verified via SET→GET roundtrip testing (2026-06-04).

### Pitch Block — Virtual Capo Shift (signed integer)

Pitch Shift1-4 parameters use a unique encoding:
- **SET**: Send semitone value as raw float (e.g., -1.0 for down 1 semitone)
- **GET**: Stored as 16-bit two's complement integer in block data
  - raw 0-24 = positive semitones (0 to +24)
  - raw 65535 = -1, raw 65534 = -2, etc. (65536 - |semitones|)
- **Range**: ±24 semitones (±2 octaves)
- **Decode formula**: `value = raw if raw <= 32767 else raw - 65536`

Confirmed via Wireshark capture (2026-05-27).

### Frequency Parameter Storage (Log Scale)

Frequency parameters are stored internally using logarithmic scale:
```
Encode: raw = 65534 × log₁₀(freq / 20) / log₁₀(max_freq / 20)
Decode: freq = 20 × 10^(raw / 65534 × log₁₀(max_freq / 20))
```
Where min_freq = 20 Hz (fixed), max_freq depends on block/type (typically 20000 Hz).

## Effect Type param_id per Block

The Type parameter ID varies by block. `fm9_set_effect_type` uses the correct ID automatically.

| Block | Type param_id | Notes |
|-------|--------------|-------|
| Amp 1 | 10 (0x0A) | |
| Drive 1 | 0 (0x00) | |
| Delay 1 | 11 (0x0B) | |
| Reverb 1 | 10 (0x0A) | |
| Chorus 1 | 0 (0x00) | |
| Flanger 1 | 0 (0x00) | |
| Phaser 1 | 0 (0x00) | |
| Pitch 1 | 0 (0x00) | |
| Wah 1 | 0 (0x00) | |
| Tremolo/Panner 1 | 0 (0x00) | |
| Compressor 1 | 12 (0x0C) | |
| Graphic EQ 1 | 15 (0x0F) | |
| Enhancer 1 | 6 (0x06) | |
| Volume/Pan 1 | 9 (0x09) | |
| Megatap Delay 1 | 28 (0x1C) | |
| Ring Modulator | 10 (0x0A) | |
| Ten-Tap Delay 1 | 0 (0x00) | |

Type is set using raw float encoding (integer as IEEE 754 float), NOT the legacy _send_sub09 enum format.

## Known Block IDs

| ID (dec) | ID (hex) | Block | Notes |
|----------|----------|-------|-------|
| 46 | 0x2E | Compressor 1 | |
| 50 | 0x32 | Graphic EQ 1 | |
| 54 | 0x36 | Parametric EQ 1 | |
| 58 | 0x3A | Amp 1 | |
| 59 | 0x3B | Amp 2 | |
| 62 | 0x3E | Cab 1 | |
| 63 | 0x3F | Cab 2 | |
| 66 | 0x42 | Reverb 1 | |
| 70 | 0x46 | Delay 1 | |
| 74 | 0x4A | Multitap Delay 1 | |
| 78 | 0x4E | Chorus 1 | |
| 82 | 0x52 | Flanger 1 | |
| 86 | 0x56 | Rotary 1 | |
| 90 | 0x5A | Phaser 1 | |
| 94 | 0x5E | Wah 1 | |
| 98 | 0x62 | Formant 1 | |
| 102 | 0x66 | Volume/Pan 1 | |
| 106 | 0x6A | Tremolo/Panner 1 | |
| 110 | 0x6E | Pitch 1 | |
| 114 | 0x72 | Filter 1 | |
| 118 | 0x76 | Drive 1 | |
| 122 | 0x7A | Enhancer 1 | |
| 130 | 0x82 | Synth 1 | >0x7F |
| 146 | 0x92 | Gate/Expander 1 | >0x7F |

Full list (89 blocks): see `fm9_blocks.json`
