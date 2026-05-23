# FM9 Tone Assistant — AI-Powered Guitar Tone Control via MCP

Control your Fractal Audio FM9 (and Axe-Fx III) in real-time through natural language conversation. Built as an [MCP](https://modelcontextprotocol.io/) server that connects any MCP-compatible AI assistant (Claude, Kiro, etc.) directly to your hardware via USB MIDI SysEx.

> "Make it crunchier" → AI adjusts amp gain in real-time while you play.

## Demo

[YouTube Demo Video](TODO)

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
| `fm9_add_block` | Add effect block to grid |
| `fm9_delete_block` | Remove block from grid |
| `fm9_move_block` | Move block to different position |
| `fm9_connect_blocks` | Connect blocks with cable (auto-shunt) |
| `fm9_disconnect_blocks` | Remove cable connection |
| `fm9_read_grid` | Read full grid layout with cable info |
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
      "args": ["path/to/fm9_tone_assistant/server.py", "--device", "fm9"]
    }
  }
}
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
- **Parameter control**: GET (func 0x1F) → Modify → PUT (func 0x74/75/76)
- **Grid layout**: sub=0x2E query returns 753-byte bitstream-encoded grid map
- **Block routing**: sub=0x30/0x32/0x33/0x35/0x36 for add/delete/move/connect

## Credits

- Protocol RE inspired by [vangrieg/Midi-SysEx-MCPServer](https://github.com/vangrieg/Midi-SysEx-MCPServer)
- Fractool by AlGrenadine for CSV format reference
- Built with [Kiro](https://kiro.dev) AI development environment

## License

MIT

## Status

**Proof of Concept** — functional but not production-ready.

### What works
- Amp 1 / Drive 1: full model selection + 13/6 parameters mapped
- Delay 1 / Reverb 1 / Cab 1 / GEQ / Enhance / Chorus 1: partial parameter maps
- Grid operations: add, delete, move, connect, disconnect, read
- Preset management: store, change, rename

### Known Issues
- **Amp 1 parameter map has incorrect offsets** — Some parameters (notably Level, and possibly others) are mapped to wrong positions. The EQ knobs (Bass/Mid/Treble), Gain, Master, and Presence appear to work correctly, but Level and switch parameters (Bright/Boost/Fat) need re-verification. A full re-scan using the AppleScript automated mapper is planned.
- Drive 1 parameter map may have similar issues (fewer parameters, less likely)

### What's missing
- Most block types have no parameter maps yet (PEQ, Gate, Pitch, Filter, Comp, Wah, Flanger, Phaser, etc.)
- No Delay/Reverb time sync or tap tempo
- No modifier/controller support
- No scene-level parameter overrides
- Error recovery is minimal (MIDI port errors require manual restart)
- Block IDs > 0x7F (Gate=0x92, Rotary=0x82) need STATUS DUMP cross-reference for grid reading

### Contributing

Parameter maps are the biggest gap. If you have a Mac with FM9 Editor, the automated AppleScript scanner (`full_tab_scan.py`) can map any block's parameters in ~30 minutes. PRs welcome.
