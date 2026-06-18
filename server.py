"""Fractal Audio Tone Assistant — MCP Server for FM9 / Axe-Fx III control."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from tools import DEVICE

# --- MCP Server ---

mcp = FastMCP(
    f"{DEVICE.name} Tone Assistant",
    instructions=f"Control Fractal Audio {DEVICE.name} amp and drive parameters via USB MIDI SysEx.",
)

# --- Register Tools ---

from tools import amp_drive, generic_block, grid_routing, preset, lookup, lab, advisor

amp_drive.register(mcp)
generic_block.register(mcp)
grid_routing.register(mcp)
preset.register(mcp)
lookup.register(mcp)
lab.register(mcp)
advisor.register(mcp)

# --- Entry Point ---

if __name__ == "__main__":
    mcp.run(transport="stdio")
