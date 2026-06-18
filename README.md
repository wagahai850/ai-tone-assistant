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

## Available MCP Tools (39 total)

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

### Tone Advisor (optional, requires AWS Bedrock)
| Tool | Description |
|------|-------------|
| `fm9_tone_advisor` | Get parameter suggestions from a specialist AI sound engineer |

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
- `boto3` (optional, for Tone Advisor)
- Fractal Audio FM9 or Axe-Fx III connected via USB
- An MCP-compatible AI client

## Setup

```bash
pip install mido python-rtmidi mcp
# Optional: for Tone Advisor
pip install boto3
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

### Tone Advisor (Optional)

The Tone Advisor delegates tone decisions to a dedicated LLM call (AWS Bedrock Converse API) with a focused sound engineering persona — separate from the orchestrating agent's context. This can produce higher-quality parameter suggestions by eliminating context pollution from non-audio concerns.

**Architecture:**

```
Orchestrator (Kiro/Claude) ←→ fm9_tone_advisor ←→ AWS Bedrock Converse API
      ↓                                                     ↓
  Reads state, executes                    Focused system prompt:
  fm9_set_* tools                          "You are a sound engineer..."
```

**Enable:**

```json
{
  "mcpServers": {
    "fm9-tone-assistant": {
      "command": "python",
      "args": ["path/to/ai-tone-assistant/server.py", "--device", "fm9"],
      "env": {
        "TONE_ADVISOR_ENABLED": "on"
      }
    }
  }
}
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TONE_ADVISOR_ENABLED` | `off` | Set to `on` to enable Bedrock calls |
| `TONE_ADVISOR_MODEL` | `sonnet-4.6` | Friendly name or full Bedrock model ID (see below) |
| `TONE_ADVISOR_MAX_TOKENS` | `2048` | Max response tokens |
| `TONE_ADVISOR_THINKING_BUDGET` | `4096` | Token budget for extended thinking |

**Model presets (friendly names → cross-region inference profiles):**

| Friendly Name | Bedrock Inference Profile ID |
|---------------|-----------------|
| `sonnet-4.6` (default) | `global.anthropic.claude-sonnet-4-6` |
| `sonnet-4.5` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `haiku-4.5` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `opus-4.8` | `us.anthropic.claude-opus-4-8` |
| `opus-4.7` | `us.anthropic.claude-opus-4-7` |

Set `TONE_ADVISOR_MODEL` to a friendly name or any full Bedrock model ID directly.
You can also override per-call via the `model` parameter.

**Usage modes:**

- `mode="advise"` — Calls Bedrock, returns parameter suggestions (costs API tokens)
- `mode="dry"` — Returns the constructed prompt without calling Bedrock ($0, for debugging/A-B testing)

**Extended thinking:** Pass `thinking=True` to see the model's reasoning chain. Useful for prompt tuning — reveals _why_ the advisor chose specific parameters. Temperature is forced to 1.0 when thinking is enabled (Anthropic requirement).

**A/B testing:** Leave `TONE_ADVISOR_ENABLED=off` for normal use (orchestrator handles everything). Set to `on` when you want to compare specialist output. The `dry` mode always works regardless of the enabled flag, so you can inspect prompts without any API cost.

**Requires:** `boto3` (`pip install boto3`) + AWS credentials via default chain (env vars, `~/.aws/credentials`, IAM role). No explicit region or profile config needed — follows your system's boto3 defaults.

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
│   ├── lookup.py          ← Wiki reference search + optional RAG augmentation
│   ├── rag.py             ← RAG engine (ChromaDB + sentence-transformers)
│   ├── advisor.py         ← Tone Advisor (optional Bedrock Converse API specialist)
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
│   ├── RAG.md             ← RAG implementation & evaluation docs
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
        "decode_scale": "4096"
      },
      "14": {
        "name": "DELAY_FEED",
        "display_name": "Feed",
        "type": "bipolar",
        "max": 100.0,
        "min": -100.0,
        "decode_style": "center"
      },
      "42": {
        "name": "DELAY_SPLICETIME",
        "display_name": "Splicetime",
        "type": "continuous",
        "max": 1000.0,
        "min": 0,
        "decode_max": 500.0
      }
    }
  }
}
```

- **block_id_base** + instance number → actual block_id (`Delay 2` = 70 + 1 = 71)
- **decode_scale**: `"4096"` for 4096-scale params (flags=0x0430, only 4 in firmware)
- **decode_max**: Calibrated max for GET decode (omitted when == display `max`)
- **decode_style**: `"center"` (raw=32767 is zero), `"zero"` (bipolar with raw=0 at min), or `"frequency"` (log scale)
- **39 blocks, 1380 parameters** with type/max/min metadata

### Encoding Rules (Confirmed 2026-06-04)

**SET (sub=0x09)** — All effect blocks use unified normalized encoding:

| Parameter type | Encoding | Formula |
|---|---|---|
| Continuous | normalized 0.0–1.0 | `value / display_max` |
| Bipolar | normalized ±1.0 | `value / display_max` (FM9 interprets ± direction) |
| Switch | raw_float | `0.0` or `1.0` |
| Enum | raw_float | integer index as float |
| Signed int | raw_float | semitone value directly |
| Frequency | raw_float | Hz value directly (FM9 applies log transform internally) |

Amp/Drive continuous params also use normalized (`value / max`).
Amp/Drive bipolar params (Level, Balance) use raw_float (display value directly).

**GET (func=0x1F)** — Six decode patterns (confirmed 2026-06-04):

| Pattern | Condition | Formula |
|---|---|---|
| 4096 scale | `cache_flags == 0x0430` (4 params) | `(raw + 4) / 4096 * display_max` |
| center bipolar | `decode_style == "center"` | `(raw - 32767) / 32767 * decode_max` |
| zero bipolar | `decode_style == "zero"` + bipolar | `raw / 65534 * decode_max - decode_max/2` |
| continuous | default | `raw / 65534 * decode_max` |
| frequency (log) | type=frequency + max≥2000 | `min * 10^(raw/65534 * log₁₀(decode_max/min))` |
| signed_int | type=signed_int | `raw if raw≤32767 else raw-65536` |

**Key insight**: SET and GET use different max values. SET uses `display_max` (from cache).
GET uses `decode_max` (internal storage range, measured via roundtrip calibration).
`decode_max` cannot be derived from cache — live calibration required.

### Firmware Update Workflow

```bash
# 1. Connect FM9 to FM9-Edit (generates new effectDefinitions cache)
# 2. Parse cache and update all_params.json:
python3 pipeline/parse_cache_v5.py --apply
# 3. Re-calibrate decode parameters:
python3 tests/calibrate_and_verify.py --all --apply
# 4. Sweep type-specific params:
python3 tests/calibrate_and_verify.py --all-types --apply
# 5. Restart MCP server to pick up changes
```

### Calibration Workflow

After any change to all_params.json (firmware update, cache re-parse):

```bash
# Calibrate a single block:
python3 tests/calibrate_and_verify.py --block "Delay 1" --apply

# Calibrate all effect blocks (requires FM9 connected, ~1 hour):
caffeinate -i python3 -u tests/calibrate_and_verify.py --all --apply 2>&1 | tee tests/calibration_log_$(date +%Y%m%d).txt

# Calibrate multi-variant blocks across all effect types (~30 min additional):
caffeinate -i python3 -u tests/calibrate_and_verify.py --all-types --apply 2>&1 | tee tests/calibration_log_alltypes_$(date +%Y%m%d).txt

# Sweep uncalibrated params across all types (brute-force, hours):
caffeinate -i python3 -u tests/calibrate_and_verify.py --sweep-unresponsive --apply 2>&1 | tee tests/calibration_log_sweep_$(date +%Y%m%d).txt

# Resume after firmware panic:
caffeinate -i python3 -u tests/calibrate_and_verify.py --all --apply --start-from "Chorus 1" 2>&1 | tee -a tests/calibration_log.txt
```

This measures the actual `decode_max`, `decode_style`, and `decode_scale` for each parameter by:
1. SET 0 (or min) → read raw → determine if center-offset (raw≈32767) or zero-based (raw≈0)
2. SET test value → read raw → compute internal storage max
3. Static detection of 4096-scale params via cache flags (no hardware needed)

Results are applied per-block (survives interruption) and merged into `calibration_results.json`.

**Current coverage** (2026-06-13): 382/661 calibratable params marked (**57.8%**).
Remaining ~279 are type-specific params confirmed unresponsive across all available types
(firmware-reserved slots). See `pipeline/README.md` for per-block status.

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
- **Channel control**: 4 channels stored contiguously, stride = (combined_length - 7) // 4; must strip checksum byte from each chunk before concatenation
- **Grid layout**: sub=0x2E query returns 753-byte bitstream-encoded grid map
- **Block routing**: sub=0x30/0x32/0x33/0x35/0x36 for add/delete/move/connect
- **Block ID encoding**: 2-byte split for IDs > 0x7F (Gate=0x92, Synth=0x82, etc.)

## Roadmap

### API Refactoring: Declarative Scene/Channel Targeting — In Progress

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

### Knowledge Base: Fractal Wiki RAG ✅

**Implemented.** See **[docs/RAG.md](docs/RAG.md)** for full documentation.

Local RAG using ChromaDB + sentence-transformers. Entire Fractal Audio Wiki (113 pages, 12,406 chunks) embedded locally. Toggled via `TONE_ASSISTANT_RAG=on` environment variable. Augments existing lookup tools with semantically relevant knowledge — no external service dependency.

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

## Related Projects

- **[mcp-midi-control](https://github.com/TheAndrewStaker/mcp-midi-control)** — A multi-device MCP server by Andrew Staker supporting Fractal AM4, Axe-Fx II/III, FM3/FM9, and ASM Hydrasynth. Cross-validated our FM9 parameter catalog against their device-true ranges (mined from FM9-Edit), which corrected 247 param type classifications. Their full roundtrip probe infrastructure also confirmed our SET/GET wire path on hardware.

## Credits

- **Architect**: wagahai850 (system design, decisions)
- **Implementation**: Kiro AI (code, MCP server, protocol RE)
- Protocol RE inspired by [vangrieg/Midi-SysEx-MCPServer](https://github.com/vangrieg/Midi-SysEx-MCPServer)
- Fractool by AlGrenadine for CSV format reference
- Built with [Kiro](https://kiro.dev) AI development environment

## License

MIT
