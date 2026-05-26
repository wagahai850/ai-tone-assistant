# FM9 Tone Assistant — AI-Powered Guitar Tone Control via MCP

Control your Fractal Audio FM9 (and Axe-Fx III) in real-time through natural language conversation. Built as an [MCP](https://modelcontextprotocol.io/) server that connects any MCP-compatible AI assistant (Claude, Kiro, etc.) directly to your hardware via USB MIDI SysEx.

> "Build me a crunch tone. JCM800 with a Tube Screamer in front." → Done in seconds.
>
> "Give me SRV's Little Wing tone." → Vibroverb + TS808, dialed in and ready to play.
>
> "Too gainy. Back off the drive." → Parameters adjusted in real-time while you play.

## Demo

[![Demo Video](https://img.youtube.com/vi/Jh07yhjfunU/maxresdefault.jpg)](https://www.youtube.com/watch?v=Jh07yhjfunU)

## What It Does

- **Build presets from scratch** — Add blocks, connect cables, set routing via chat
- **Real-time parameter control** — Adjust amp/drive/delay/reverb parameters by talking
- **Model selection** — "Give me a JCM800 tone" → sets Brit 800 2204 High + appropriate EQ
- **Read grid layout** — Query current preset structure including cable connections
- **Full preset management** — Store, rename, change presets

## How It Works

```
┌─────────────────────────────────────┐
│  AI Assistant (Claude/Kiro/etc.)    │
│  "Make it less gainy"              │
│       ↓ MCP tool call              │
├─────────── MCP Protocol ───────────┤
│  FM9 Tone Assistant (Python)       │
│  ├── Parameter maps (JSON)         │
│  ├── Amp/Drive model database      │
│  └── USB MIDI SysEx engine         │
│       ↓                            │
│  FM9 / Axe-Fx III (USB)           │
└─────────────────────────────────────┘
```

The entire FM9 USB MIDI protocol was reverse-engineered from scratch using Wireshark USB captures of the FM9 Editor communication. No official documentation exists for most of these commands.

## Available MCP Tools

### Core Control
| Tool | Description |
|------|-------------|
| `fm9_get_status` | Connection state + block bypass/channel status |
| `fm9_set_amp_type` | Change amp model by name |
| `fm9_set_amp_params` | Set amp parameters (gain, EQ, master, etc.) |
| `fm9_get_amp_params` | Read current amp parameters |
| `fm9_set_drive_type` | Change drive model by name |
| `fm9_set_drive_params` | Set drive parameters |
| `fm9_get_drive_params` | Read current drive parameters |
| `fm9_set_scene` | Switch scene (1-8) |
| `fm9_set_bypass` | Bypass/engage any effect block |
| `fm9_set_channel` | Switch block channel (A/B/C/D) |
| `fm9_set_cab_ir` | Select cabinet IR |

### Generic Block Control (all 40 blocks)
| Tool | Description |
|------|-------------|
| `fm9_get_block_params` | Read parameters for any block (display values with type info) |
| `fm9_set_block_params` | Set parameters on any block (normalized 0-1) |
| `fm9_list_block_params` | List parameter names/IDs/type/min/max for a block |
| `fm9_list_effect_types` | List available types/models for a block category |
| `fm9_set_effect_type` | Change effect type/model for any block |

### Reference / Lookup
| Tool | Description |
|------|-------------|
| `fm9_lookup_model_info` | Search amp/drive model info (based-on, cab, notes) |
| `fm9_lookup_block_info` | Query type-specific valid parameters |

### Grid / Routing
| Tool | Description |
|------|-------------|
| `fm9_add_block` | Add effect block to grid (upsert — replaces existing) |
| `fm9_delete_block` | Remove block from grid |
| `fm9_move_block` | Move block to different position |
| `fm9_connect_blocks` | Connect blocks with cable (auto-shunt, cross-row supported) |
| `fm9_disconnect_blocks` | Remove cable connection (same-row or cross-row) |
| `fm9_read_grid` | Read full grid layout with cable info |
| `fm9_read_graph` | Read preset as signal-flow graph (blocks + connections) |
| `fm9_apply_graph` | Build preset from graph (declarative, auto-layout) |

### Preset Management
| Tool | Description |
|------|-------------|
| `fm9_store_preset` | Save preset to flash |
| `fm9_change_preset` | Switch to different preset |
| `fm9_set_preset_name` | Rename preset |
| `fm9_list_amp_types` | Search amp models |
| `fm9_list_drive_types` | Search drive models |

## Requirements

- Python 3.10+
- `mido` + `python-rtmidi`
- `mcp` (FastMCP)
- Fractal Audio FM9 or Axe-Fx III connected via USB
- An MCP-compatible AI client

## Setup

```bash
pip install mido python-rtmidi mcp
```

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "fm9-tone-assistant": {
      "command": "python",
      "args": ["path/to/ai-tone-assistant/server.py", "--device", "fm9"]
    }
  }
}
```

### Project Structure

```
ai-tone-assistant/
├── server.py          ← Entry point (thin: MCP init + tool registration)
├── fm9_midi.py        ← MIDI communication layer (SysEx engine)
├── tools/             ← MCP tool definitions (by category)
│   ├── __init__.py    ← Shared state, data loading, encoding helpers
│   ├── amp_drive.py   ← Amp/Drive (display-value scaling)
│   ├── generic_block.py ← Any block (normalized 0-1)
│   ├── grid_routing.py  ← Grid layout operations
│   ├── preset.py      ← Scene/bypass/channel/store/name
│   ├── lookup.py      ← Wiki reference search
│   └── lab.py         ← RE/debug (raw sysex, snapshot, diff)
├── data/fm9/          ← Runtime data (JSON, committed)
│   ├── amp_types.json, drive_types.json
│   ├── amp_params.json, drive_params.json
│   ├── blocks.json, all_params.json (with meta: type/min/max)
│   ├── effect_definitions.json
│   ├── wiki_models.json, wiki_blocks.json
│   └── type_valid_params.json
├── docs/              ← Protocol documentation
│   ├── PROTOCOL.md
│   └── REVERSE_ENGINEERING.md
├── pipeline/          ← RE scripts (.gitignore'd)
├── README.md
└── LICENSE
```

### Device Selection

| `--device` | Hardware |
|------------|----------|
| `fm9` (default) | Fractal Audio FM9 |
| `axe3` | Fractal Audio Axe-Fx III |
| `fm3` | Fractal Audio FM3 |

MIDI port names are auto-detected. If detection fails, the server will print available ports and exit.

## Supported Devices

| Device | Status |
|--------|--------|
| FM9 | ✅ Fully tested |
| Axe-Fx III | ✅ Supported (same protocol, different model_id) |
| FM3 | 🔄 Should work (untested) |

## Protocol Documentation

The reverse-engineered FM9 USB MIDI protocol is documented in detail in the project notes. Key discoveries:

- **Checksum**: `XOR(model_id, func, data...) ^ 0x05 & 0x7F`
- **Parameter control**: sub=0x09 (value set) and sub=0x52 (real-time slide) with IEEE 754 float encoding
- **Channel control**: Direct channel targeting via payload byte (A=0x00, B=0x20, C=0x40, D=0x60)
- **Grid layout**: sub=0x2E query returns 753-byte bitstream-encoded grid map
- **Block routing**: sub=0x30/0x32/0x33/0x35/0x36 for add/delete/move/connect
- **Shunt placement**: sub=0x32 with sequential index per shunt (byte[3] must be unique in preset)
- **Block ID encoding**: 2-byte split (`id & 0x7F`, `id >> 7`) supports all blocks including >0x7F (Gate, Synth, etc.)

## Credits

- Protocol RE inspired by [vangrieg/Midi-SysEx-MCPServer](https://github.com/vangrieg/Midi-SysEx-MCPServer)
- Fractool by AlGrenadine for CSV format reference
- Built with [Kiro](https://kiro.dev) AI development environment

## License

MIT

## Status

**Working Proof of Concept** — all blocks controllable, core workflow functional.

### What works
- **All 40 effect blocks**: parameter read/write with display values (type-aware decoding)
- **1321 parameters mapped**: all with type/min/max metadata (102 hand-verified, 1219 pattern-inferred)
- **Amp 1**: full model selection (331 models) + display-value parameter control (Gain=5.0, etc.)
- **Drive 1**: full model selection (86 models) + display-value parameter control
- **Delay/Reverb/Chorus/etc.**: parameter control via `fm9_set_block_params` (verified on Delay)
- **All blocks**: channel control (A/B/C/D), bypass, scene switching
- **Grid operations**: add, delete, move, connect, disconnect, read
- **Preset management**: store, change, rename, query name by number
- **Model/type lookup**: 331 amp models, 86 drive models, 29 delay types, 79 reverb types, 2000+ cab IRs
- **Type-specific valid parameters**: know which params are active for each model variant (331 amp types, 16 pitch types, 11 compressor types, etc.)
- **Axe-Fx III support**: same protocol, parameter data extracted via automated pipeline

### Known Limitations
- **`fm9_get_status` reports incorrect preset number** — `func=0x0D` returns a stale/incorrect preset number. `change_preset` works correctly (FM9 switches presets) but the query response is unreliable. Under investigation.
- **Generic block tools use normalized 0-1 values** — The `fm9_set_block_params` tool sends values as 0.0-1.0 (normalized). Only Amp and Drive have dedicated tools with display-value scaling (e.g., "Gain=5.0" maps to 0-10 range). Other blocks require the caller to normalize manually.
- **Parameter min/max are inferred for most blocks** — Amp and Drive have hand-verified ranges. All other blocks have pattern-matched metadata (type/min/max) that is mostly correct but not guaranteed. The `verified` flag in `fm9_list_block_params` output indicates confidence level.
- **Parameter IDs differ between Axe-Fx III and FM9** — Same block type can have different param_id mappings. Each device has its own extracted parameter data.
- **Amp "Presence" varies by model** — Preamp-only models use "Preamp Presence" (param_id=137), full amp models use "Presence" (param_id=30)
- **No Delay/Reverb time sync or tap tempo**
- **No modifier/controller support**
- **No scene-level parameter overrides**
- **Error recovery is minimal** — MIDI port errors require server restart

### Roadmap
1. Hand-verify min/max for remaining blocks (promote inferred → verified)
2. Modifier/controller assignment support
3. Scene-level parameter management
4. Direct firmware query for effect definitions (eliminate Editor cache dependency)
5. Demo video re-record

### Data Pipeline

Parameter maps and model names are extracted automatically from the Editor binary and firmware cache:

```bash
# Run after firmware update (from project root):
python3 pipeline/pipeline_params.py fm9       # Extract param tables + type-valid params
python3 pipeline/pipeline_params.py axe3      # Same for Axe-Fx III
python3 pipeline/pipeline_effect_defs.py fm9  # Extract model/type names from cache
python3 pipeline/pipeline_effect_defs.py axe3

# Rebuild Wiki reference data (requires pandoc):
python3 pipeline/build_wiki_data.py --fetch   # Re-download and parse from wiki.fractalaudio.com
```

### Contributing

The automated pipeline handles parameter extraction. If you want to help:
- **min/max values**: Run the param scanner on blocks to determine display ranges
- **Type-specific behavior**: Document which params are ignored for specific model types
- **FM3 testing**: Same protocol should work, needs verification

PRs welcome.
