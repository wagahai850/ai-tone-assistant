# FM9 Tone Assistant — AI-Powered Guitar Tone Control via MCP

Control your Fractal Audio FM9 (and Axe-Fx III) in real-time through natural language conversation. Built as an [MCP](https://modelcontextprotocol.io/) server that connects any MCP-compatible AI assistant (Claude, Kiro, etc.) directly to your hardware via USB MIDI SysEx.

## Philosophy

This is not "AI making music." This is a power tool for guitarists.

You play. You listen. You decide. The AI handles the engineering—translating "too harsh, needs more body" into the exact parameter changes across 1380+ knobs that would take a sound engineer to know by heart. Think of it as having a session engineer on call who speaks SysEx.

A guitarist shouldn't need to be a sound engineer, a mix engineer, AND a Fractal Audio parameter specialist to get the tone in their head out of their speakers. LLMs carry domain knowledge across all these disciplines. This tool gives them hands—direct hardware control via USB MIDI—so that knowledge becomes actionable in real-time.

**Your ears are the final authority.** The AI proposes, you dispose. It knows which of 1380 parameters to reach for when you say "too fizzy." You decide if the result sounds right.

---

> "Build me a crunch tone. JCM800 with a Tube Screamer in front." → Done in seconds.
>
> "Give me SRV's Little Wing tone." → Vibroverb + TS808, dialed in and ready to play.
>
> "Too gainy. Back off the drive." → Parameters adjusted in real-time while you play.

## Demo

[![Demo Video](https://img.youtube.com/vi/Jh07yhjfunU/maxresdefault.jpg)](https://www.youtube.com/watch?v=Jh07yhjfunU)

## POC: Live Preset Session

Built 6 live performance presets from scratch in under an hour through natural conversation — research, architecture, iterative tone dialing, all via MCP. Full report with unabridged session log: **[POC Report](docs/POC_LIVE_PRESET_SESSION.md)**

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
│  ├── all_params.json (SSOT)        │
│  ├── Amp/Drive model database      │
│  └── USB MIDI SysEx engine         │
│       ↓                            │
│  FM9 / Axe-Fx III (USB)           │
└─────────────────────────────────────┘
```

The entire FM9 USB MIDI protocol was reverse-engineered from scratch using Wireshark USB captures of the FM9 Editor communication. No official documentation exists for most of these commands.

## Available MCP Tools (38 total)

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
| `fm9_set_cab_ir` | Select cabinet IR (bank + index) |

### Generic Block Control (all effect blocks)
| Tool | Description |
|------|-------------|
| `fm9_get_block_params` | Read parameters for any block |
| `fm9_set_block_params` | Set parameters on any block |
| `fm9_list_block_params` | List parameter names/IDs/type/min/max for a block |
| `fm9_list_effect_types` | List available types/models for a block category |
| `fm9_set_effect_type` | Change effect type/model for any block |

### Grid / Routing
| Tool | Description |
|------|-------------|
| `fm9_add_block` | Add effect block to grid (upsert) |
| `fm9_delete_block` | Remove block from grid |
| `fm9_move_block` | Move block to different position |
| `fm9_connect_blocks` | Connect blocks with cable (auto-shunt, cross-row) |
| `fm9_disconnect_blocks` | Remove cable connection |
| `fm9_read_grid` | Read full grid layout with cable info |
| `fm9_read_graph` | Read preset as signal-flow graph |
| `fm9_apply_graph` | Build preset from graph (declarative, auto-layout) |

### Preset Management
| Tool | Description |
|------|-------------|
| `fm9_store_preset` | Save preset to flash |
| `fm9_change_preset` | Switch to different preset |
| `fm9_set_preset_name` | Rename preset |
| `fm9_set_scene_name` | Set scene name (1-8) |
| `fm9_list_amp_types` | Search amp models |
| `fm9_list_drive_types` | Search drive models |

### Reference / Lookup
| Tool | Description |
|------|-------------|
| `fm9_lookup_model_info` | Search amp/drive model info (based-on, cab, notes) |
| `fm9_lookup_block_info` | Query effect block wiki info |

### Lab / RE (diagnostic)
| Tool | Description |
|------|-------------|
| `fm9_get_block_data` | Raw block data dump |
| `fm9_read_param_raw` | Read raw 3-byte param value |
| `fm9_dump_block_full` | Full chunk dump |
| `fm9_send_raw_sysex` | Send arbitrary SysEx |
| `fm9_snapshot_block` | Snapshot block state for diffing |
| `fm9_diff_block` | Compare two snapshots |

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

### Steering Your AI (Recommended)

MCP gives the AI *hands* (tool access), but a **steering file** gives it *expertise* — domain knowledge about tone design workflow, parameter relationships, and how to interpret your feedback.

An example steering file is included at [`docs/STEERING_EXAMPLE.md`](docs/STEERING_EXAMPLE.md).

How to use it depends on your AI client:
- **Kiro**: Place in `.kiro/steering/` directory (auto-loaded every session)
- **Claude Desktop**: Include in your system prompt or project instructions
- **Other MCP clients**: Consult your client's documentation for context/instruction configuration

## Project Structure

```
ai-tone-assistant/
├── server.py              ← Entry point (MCP init + tool registration)
├── fractal_midi.py        ← MIDI communication layer (SysEx engine)
├── tools/                 ← MCP tool definitions (by category)
│   ├── __init__.py        ← Shared state, data loading, block resolution, encoding
│   ├── amp_drive.py       ← Amp/Drive dedicated tools (normalized encoding)
│   ├── generic_block.py   ← Any block (unified normalized encoding + calibrated decode)
│   ├── grid_routing.py    ← Grid layout + routing operations
│   ├── preset.py          ← Scene/bypass/channel/store/name
│   ├── lookup.py          ← Wiki reference search
│   └── lab.py             ← RE/debug (raw sysex, snapshot, diff)
├── data/fm9/              ← Runtime data (JSON, committed)
│   ├── all_params.json    ← SSOT: all blocks × all params × metadata + decode calibration
│   ├── amp_types.json     ← Amp model enum (type_id → name, 396 entries)
│   ├── drive_types.json   ← Drive model enum (type_id → name, 86 entries)
│   ├── effect_definitions.json ← Effect type name lists (per block category)
│   ├── type_valid_params.json  ← Amp Type-specific valid params (from XML)
│   ├── wiki_models.json   ← "Based on" info from Fractal Wiki
│   └── wiki_blocks.json   ← Block descriptions from Fractal Wiki
├── pipeline/              ← RE & data extraction scripts
│   ├── parse_cache_v5.py  ← effectDefinitions cache → all_params.json
│   └── README.md          ← Pipeline documentation
├── tests/
│   ├── test_roundtrip.py  ← Automated SET→GET verification (requires FM9)
│   ├── calibrate_decode.py ← GET decode calibration (measures decode_max per param)
│   ├── classify_failures.py ← Categorize roundtrip failures
│   └── fix_from_failures.py ← Auto-fix all_params.json from failure patterns
├── docs/
│   ├── PROTOCOL.md        ← Full SysEx protocol reference
│   ├── REVERSE_ENGINEERING.md
│   ├── POC_LIVE_PRESET_SESSION.md ← Live preset session POC report
│   └── STEERING_EXAMPLE.md
└── LICENSE (MIT)
```

## Data Architecture

### Single Source of Truth: `all_params.json`

All parameter definitions live in one file. Schema v2 with decode calibration:

```json
{
  "_meta": { "firmware": "11.0", "schema_version": 2 },
  "DELAY": {
    "block_name": "Delay",
    "block_id_base": 70,
    "max_instances": 4,
    "params": {
      "12": {
        "name": "DELAY_TIME",
        "display_name": "Time",
        "type": "continuous",
        "max": 1000.0,
        "min": 0,
        "decode_max": 16030.82,
        "decode_style": "zero"
      },
      "14": {
        "name": "DELAY_FEED",
        "display_name": "Feed",
        "type": "bipolar",
        "max": 100.0,
        "min": -100.0,
        "decode_style": "center"
      }
    }
  }
}
```

- **block_id_base** + instance number → actual block_id (`Delay 2` = 70 + 1 = 71)
- **decode_max**: Calibrated max for GET decode (may differ from display `max`)
- **decode_style**: `"center"` (raw=32767 is zero, true bipolar) or `"zero"` (raw=0 is min)
- **39 blocks, 1380 parameters** with type/max/min metadata

### Encoding Rules (Confirmed 2026-05-29)

**SET (sub=0x09)** — All effect blocks use unified normalized encoding:

| Parameter type | Encoding | Formula |
|---|---|---|
| Continuous | normalized 0.0–1.0 | `value / display_max` |
| Bipolar | normalized ±1.0 | `value / display_max` (FM9 interprets ± direction) |
| Switch | raw_float | `0.0` or `1.0` |
| Enum | raw_float | integer index as float |
| Signed int | raw_float | semitone value directly |

Amp/Drive continuous params also use normalized (`value / max`).
Amp/Drive bipolar params (Level, Balance) use raw_float (display value directly).

**GET (func=0x1F)** — 21-bit integer (3×7-bit packed), decode depends on calibration:

| decode_style | Formula |
|---|---|
| `"center"` | `(raw - 32767) / 32767 * decode_max` |
| `"zero"` or default continuous | `raw / 65534 * decode_max` |
| uncalibrated bipolar | `raw / 65534 * (max - min) + min` |

**Key insight**: SET and GET use different max values. SET uses `display_max` (from cache).
GET uses `decode_max` (internal storage range, measured via roundtrip calibration).

### Firmware Update Workflow

```bash
# 1. Connect FM9 to FM9-Edit (generates new effectDefinitions cache)
# 2. Parse cache and update all_params.json:
python3 pipeline/parse_cache_v5.py --apply
# 3. Re-calibrate decode parameters:
python3 tests/calibrate_decode.py --all --apply
# 4. Verify roundtrip:
python3 tests/test_roundtrip.py
# 5. Restart MCP server to pick up changes
```

### Calibration Workflow

After any change to all_params.json (firmware update, cache re-parse):

```bash
# Calibrate a single block:
python3 tests/calibrate_decode.py --block "Delay 1" --apply

# Calibrate all effect blocks (takes ~5 min, requires FM9 connected):
python3 tests/calibrate_decode.py --all --apply
```

This measures the actual `decode_max` and `decode_style` for each parameter by:
1. SET a known value → read raw from GET → compute internal storage max
2. SET 0 → read raw → determine if center-offset (raw≈32767) or zero-based (raw≈0)

## Device Support

| Device | `--device` flag | Status |
|--------|----------------|--------|
| FM9 | `fm9` (default) | ✅ Fully tested |
| Axe-Fx III | `axe3` | ✅ Supported (same protocol) |
| FM3 | `fm3` | 🔄 Should work (untested) |

## Protocol Documentation

The reverse-engineered FM9 USB MIDI protocol is documented in [`docs/PROTOCOL.md`](docs/PROTOCOL.md). Key discoveries:

- **Checksum**: `XOR(model_id, func, data...) ^ 0x05 & 0x7F`
- **Parameter control**: sub=0x09 with IEEE 754 float encoding (5×7-bit packed)
- **Channel control**: 4 channels stored contiguously, stride = (combined_length - 7) // 4
- **Grid layout**: sub=0x2E query returns 753-byte bitstream-encoded grid map
- **Block routing**: sub=0x30/0x32/0x33/0x35/0x36 for add/delete/move/connect
- **Block ID encoding**: 2-byte split for IDs > 0x7F (Gate=0x92, Synth=0x82, etc.)

## Roadmap

### API Refactoring: Declarative Scene/Channel Targeting

Current API requires sequential state changes to target a specific Scene + Channel:

```python
# Current (imperative, error-prone):
fm9_set_scene(scene=2)
fm9_set_channel(block="Amp 1", channel="B")
fm9_set_amp_params(params={"Gain": 8.0})
fm9_set_scene(scene=1)  # restore
```

Planned refactoring adds `scene` and `channel` as optional parameters to SET/GET tools:

```python
# Planned (declarative, atomic):
fm9_set_amp_params(params={"Gain": 8.0}, scene=2, channel="B")
```

This separates "where to write" from "what to write" and eliminates an entire class of bugs where Scene/Channel state drifts between calls. The MCP server handles state transitions internally.

**Data model implications**: Block parameter storage needs to be restructured around a `Block → Channel → Parameter` hierarchy with Scene as an orthogonal axis controlling which Channel is active. Current flat parameter access doesn't model this relationship explicitly.

### Knowledge Base: Fractal Wiki RAG

The [POC session](docs/POC_LIVE_PRESET_SESSION.md) revealed that the AI has strong general audio engineering knowledge but weak FM9-specific operational knowledge. For example, when a user says "half-step down," the AI needs to know that the Pitch block's Virtual Capo feature can handle this without retuning — but that's FM9-specific knowledge not reliably present in LLM training data.

**Solution**: Ingest the [Fractal Audio Wiki](https://wiki.fractalaudio.com) (111 pages of community-maintained documentation covering all blocks, parameters, amp models, and tutorials) as a RAG (Retrieval-Augmented Generation) knowledge base.

**How RAG works in this context**:

```
┌─────────────────────────────────────────────────────┐
│ Fractal Wiki (111 pages)                             │
│ Amp models, effect blocks, tutorials, tech notes     │
└──────────────────┬──────────────────────────────────┘
                   │ scrape → chunk → embed
                   ▼
┌─────────────────────────────────────────────────────┐
│ Vector Database (local, e.g. ChromaDB)               │
│ ~500-1000 text chunks with embedding vectors         │
└──────────────────┬──────────────────────────────────┘
                   │ similarity search
                   ▼
┌─────────────────────────────────────────────────────┐
│ MCP Tool: fm9_search_knowledge(query, top_k=5)       │
│                                                      │
│ User: "I need half-step down tuning"                 │
│ → query: "half step down transpose tuning"           │
│ → returns: Wiki chunks about Pitch block,            │
│   Virtual Capo, semitone shifting                    │
│ → AI: "Use Pitch block Virtual Capo, Shift = -1"    │
└─────────────────────────────────────────────────────┘
```

**Why RAG works here**: The Wiki is written in natural language with use-case descriptions ("use Virtual Capo to change tuning without retuning your guitar"), so embedding similarity search naturally connects user intent ("half-step down") to FM9 features. No manual keyword mapping needed.

**Why not full-context injection**: At 111 pages the Wiki exceeds what fits comfortably in a context window alongside steering + conversation history. RAG retrieves only the relevant chunks per query.

**Implementation plan**:
1. Scrape Wiki pages → chunk into ~500-token segments
2. Embed chunks using a local embedding model (e.g. `sentence-transformers`)
3. Store in a local vector DB (ChromaDB or FAISS) — no external service dependency
4. Expose as `fm9_search_knowledge` MCP tool
5. Auto-scrape on first run; re-scrape on firmware update

This eliminates the dependency on the user's FM9 expertise and makes the tool accessible to beginners who don't know what the hardware can do.

### Future: Device Abstraction Layer

The current implementation is FM9-specific by design. Abstraction into a device-agnostic interface will happen **when a second device implementation begins** (e.g., Line 6 Helix) — not before. Premature abstraction without a second concrete implementation leads to wrong boundaries.

**Why not now**: FM9 has concepts (Channels A/B/C/D, DynaCab, Grid coordinates) that may not exist on other platforms. The correct interface can only be discovered by comparing two implementations. Abstracting from one example is guessing.

**What we do now** (zero-cost preparation):
- Maintain clear layer separation (transport → data → domain)
- Keep `fm9_*` tool naming to make device-specificity explicit
- Mark device-specific boundaries in code ("here be dragons for abstraction")

**When the second device arrives**:
```python
class ToneDevice(Protocol):
    def set_param(self, block: str, param: str, value: float,
                  scene: int | None = None, variant: str | None = None) -> None: ...
    def get_param(self, block: str, param: str) -> float: ...
    def list_blocks(self) -> list[BlockInfo]: ...
    def apply_routing(self, graph: SignalGraph) -> None: ...

class FM9Device(ToneDevice): ...    # variant = Channel (A/B/C/D)
class HelixDevice(ToneDevice): ...  # variant = None (no equivalent concept)
```

MCP tools become device-agnostic (`tone_set_params` instead of `fm9_set_amp_params`), with device-specific behavior hidden behind the `ToneDevice` interface. Knowledge bases are per-device (`data/fm9/`, `data/helix/`).

**Timeline**: FM9 stable → second device → extract interface → generalize tools → third device onward is implementation-only.

### Speculation: LLM as the Abstraction Layer Itself

Here's a thought experiment. What if we don't write a device abstraction layer at all?

Traditional software design says: two systems with different data models need an adapter layer (interfaces, protocol classes, mapping code). But consider what actually happens in a tone design session:

```
User: "I want a JCM800 crunch tone. Solo should be high-gain with sustain."

IF the device is FM9:
  → Scene 2, Amp Channel B, Gain up, Master up for power amp saturation

IF the device is Helix:
  → Snapshot 2, Amp Gain override, Master override
```

Same musical intent, different operational steps. A human sound engineer who knows both platforms would handle this dynamically — they don't need an "abstraction layer" in their head. They just know how each device works and translate intent to action on the fly.

An LLM with device-specific knowledge (via steering + RAG) does the same thing. The "abstraction layer" is the LLM's reasoning itself. What you actually need:

1. **Thin operation APIs per device** — deterministic, device-specific, CRUD-level (`set_param`, `apply_routing`, `store_preset`)
2. **Device-specific steering** — "how to think about this device" (FM9: Scenes + Channels; Helix: Snapshots)
3. **Device-specific knowledge base** — RAG over each device's documentation

No shared interface code. No adapter pattern. The LLM dynamically resolves "sustain → which knobs on which device" every time, informed by the device's steering and KB. The non-determinism is acceptable because the user's ears close the feedback loop — tone design has no single "correct" answer anyway.

This is unproven and possibly naive. But it's worth noting that the architecture already works this way for a single device (the [POC session](docs/POC_LIVE_PRESET_SESSION.md) demonstrates it). Multi-device is an extension of the same pattern, not a fundamentally different problem.

Related reading: Fowler's ["LLMs bring new nature of abstraction"](https://martinfowler.com/articles/2025-nature-abstraction.html) (2025), Rost's ["LLM-Mediated Computing"](https://interactions.acm.org/archive/view/september-october-2025/reclaiming-the-computer-through-llm-mediated-computing) (ACM Interactions, 2025).

## Credits

- **Architect**: wagahai850 (system design, decisions)
- **Implementation**: Kiro AI (code, MCP server, protocol RE)
- Protocol RE inspired by [vangrieg/Midi-SysEx-MCPServer](https://github.com/vangrieg/Midi-SysEx-MCPServer)
- Fractool by AlGrenadine for CSV format reference
- Built with [Kiro](https://kiro.dev) AI development environment

## License

MIT
