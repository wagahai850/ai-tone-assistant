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
| 0x13 | STATUS_DUMP | (none) | Query all block states |
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
| 0x09 | OUT | SET_TYPE | Change amp/drive/IR model (enum parameter) |
| 0x16 | OUT | SET_CHANNEL | Switch block channel (A/B/C/D) |
| 0x26 | OUT | STORE_PRESET | Save preset to flash |
| 0x27 | OUT | CHANGE_PRESET | Switch to different preset |
| 0x28 | OUT | SET_PRESET_NAME | Rename preset (60 bytes, 7-bit packed name) |
| 0x2A | OUT | QUERY_PRESET_NAME | Get preset name by number |
| 0x2E | both | GRID_QUERY | Read grid layout (753-byte response) |
| 0x30 | OUT | LAYOUT_BEGIN | Start grid operation (block add/delete/move) |
| 0x32 | OUT | BLOCK_ADD | Add block at grid position |
| 0x33 | OUT | BLOCK_DELETE | Delete block at grid position |
| 0x35 | OUT | CABLE_OP | Connect/disconnect cable (26 bytes) |
| 0x36 | OUT | BLOCK_MOVE | Move block in direction |
| 0x37 | both | TIMING_SYNC | Heartbeat/timing |
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

## STATUS_DUMP (func=0x13)

Request: `F0 00 01 74 [model] 13 [cs] F7`

Response contains 3-byte packets for each active block:
```
[id_lo] [id_hi] [dd]
```
- effect_id = id_lo | (id_hi << 7)
- dd bit 0 = bypass state
- dd bits 1-3 = channel (0=A, 1=B, 2=C, 3=D)

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

## SET_TYPE (sub=0x09)

Change amp/drive model or cab IR:

```
F0 00 01 74 [model] 01 09 00 [block_id] 00 [param] 00 00 00 [id_lo] [id_hi] [id_msb] 00 00 00 00 [cs] F7
```

| block_id | param | Purpose |
|----------|-------|---------|
| 0x3A (Amp) | 0x0A | Amp model type |
| 0x76 (Drive) | 0x0A | Drive model type |
| 0x3E (Cab) | 0x04 | Cabinet IR selection |

Type ID is 21-bit: `id_lo | (id_hi << 7) | (id_msb << 14)`

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
Step 1 (sub=0x30): block_id=0x25, p=[00,00,00], d[0]=grid_position
Step 2 (sub=0x32): block_id=target, p=[00,00,00], d[0]=grid_position
```

For shunts: `p=[08,00,00]` instead of `p=[00,00,00]`

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
    d10 = (to_pos >> 2) | ((to_pos & 0x01) << 6)
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

## Known Block IDs

| ID (dec) | ID (hex) | Block | Notes |
|----------|----------|-------|-------|
| 37 | 0x25 | Input 1 | |
| 42 | 0x2A | Output 1 | |
| 46 | 0x2E | Comp 1 | |
| 50 | 0x32 | GEQ 1 | |
| 51 | 0x33 | GEQ 2 | |
| 54 | 0x36 | PEQ 1 | |
| 55 | 0x37 | PEQ 2 | |
| 58 | 0x3A | Amp 1 | |
| 59 | 0x3B | Amp 2 | |
| 62 | 0x3E | Cab 1 | |
| 63 | 0x3F | Cab 2 | |
| 66 | 0x42 | Reverb 1 | |
| 70 | 0x46 | Delay 1 | |
| 78 | 0x4E | Chorus 1 | |
| 110 | 0x6E | Pitch 1 | |
| 114 | 0x72 | Filter 1 | |
| 118 | 0x76 | Drive 1 | |
| 122 | 0x7A | Enhance | |
| 130 | 0x82 | Rotary 1 | >0x7F, grid shows 0x02 |
| 146 | 0x92 | Gate 1 | >0x7F, grid shows 0x12 |
