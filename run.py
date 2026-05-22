#!/usr/bin/env python3
"""Launcher for FM9 Tone Assistant MCP Server.
Verifies dependencies are installed, then runs server.py."""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()

# Check dependencies
try:
    import mido
    import mcp
except ImportError as e:
    print(f"Missing dependency: {e.name}", file=sys.stderr)
    print("Install with: pip install mido python-rtmidi mcp", file=sys.stderr)
    sys.exit(1)

# Run server
sys.argv = [str(SCRIPT_DIR / "server.py")] + sys.argv[1:]
sys.path.insert(0, str(SCRIPT_DIR))
import runpy
runpy.run_path(str(SCRIPT_DIR / "server.py"), run_name="__main__")
