"""Cross-server roundtrip test: compare display values between
ai-tone-assistant and mcp-midi-control for the same FM9 parameters.

Requires both MCP servers running + FM9 connected via USB.
Run manually: python tests/cross_server_roundtrip.py

Uses subprocess to call each MCP server via their respective CLIs.
TODO: Adapt to actually call both servers. For now, this is a template
that documents the test methodology — fill in the transport calls when
the terminal is available.
"""

import json
import subprocess
import sys
from pathlib import Path

# Configuration
BLOCKS_TO_TEST = ["amp", "drive", "reverb"]
CHANNEL = "C"  # Amp is on Channel C in current preset

# Parameters to compare per block (param_name_ours, param_name_theirs)
# Some names differ between projects due to alias resolution
PARAM_MAP = {
    "amp": [
        ("Gain", "drive"),  # ours: "Gain", theirs resolves "gain" -> "drive"
        ("Bass", "bass"),
        ("Mid", "mid"),
        ("Treble", "treble"),
        ("Master Volume", "master"),
        ("Presence", "presence"),
        ("Depth", "depth"),
        ("Level", "level"),
        ("Balance", "balance"),
        ("High Cut Frequency", "hicut"),
        ("Low Cut Frequency", "locut"),
        ("Negative Feedback", "negfdbk"),
        ("Supply Sag", "sag"),
        ("Presence Frequency", "presfreq"),
    ],
    "drive": [
        ("Drive", "drive"),
        ("Tone", "tone"),
        ("Level", "level"),
        ("Mix", "mix"),
        ("Bass", "bass"),
        ("Mid", "mid"),
        ("Treble", "treble"),
        ("Bias", "bias"),
        ("Low Cut", "locut"),
        ("High Cut", "hicut"),
    ],
    "reverb": [
        ("Mix", "mix"),
        ("Level", "level"),
        ("Time", "time"),
        ("Pre-Delay", "predelay"),
        ("High Cut", "hicut"),
        ("Low Cut", "locut"),
        ("Size", "size"),
        ("Diffusion", "diffusion"),
    ],
}


def get_ours(block: str, channel: str) -> dict:
    """Get all params from ai-tone-assistant.
    
    TODO: Replace with actual MCP call when available.
    For now, returns a placeholder.
    """
    # This would call: fm9_get_amp_params(channel=channel) or fm9_get_block_params(block, channel)
    raise NotImplementedError("Needs MCP transport - run via Kiro chat or implement stdio call")


def get_theirs(block: str, param: str, channel: str) -> dict:
    """Get one param from mcp-midi-control.
    
    TODO: Replace with actual MCP call when available.
    """
    # This would call: get_param(port="fm9", block=block, name=param, channel=channel)
    raise NotImplementedError("Needs MCP transport - run via Kiro chat or implement stdio call")


def compare_values(ours: float, theirs: float, param_name: str, tolerance: float = 0.02) -> bool:
    """Compare two display values with tolerance for rounding differences."""
    if ours is None or theirs is None:
        return False
    diff = abs(ours - theirs)
    # For values near zero, use absolute tolerance
    if abs(ours) < 1.0 and abs(theirs) < 1.0:
        return diff < tolerance
    # For larger values, use relative tolerance
    max_val = max(abs(ours), abs(theirs))
    return diff / max_val < 0.01  # 1% relative tolerance


def main():
    """Run cross-server comparison and report mismatches."""
    print("Cross-Server Roundtrip Test")
    print("=" * 60)
    print(f"Channel: {CHANNEL}")
    print()

    results = []
    mismatches = []

    for block in BLOCKS_TO_TEST:
        print(f"\n--- {block.upper()} ---")
        params = PARAM_MAP.get(block, [])
        
        for our_name, their_name in params:
            try:
                our_value = get_ours(block, CHANNEL).get(our_name)
                their_result = get_theirs(block, their_name, CHANNEL)
                their_value = their_result.get("display_value")
                wire = their_result.get("wire_value")
                
                match = compare_values(our_value, their_value, our_name)
                status = "✅" if match else "❌"
                
                result = {
                    "block": block,
                    "param": our_name,
                    "ours": our_value,
                    "theirs": their_value,
                    "wire": wire,
                    "match": match,
                }
                results.append(result)
                
                if not match:
                    mismatches.append(result)
                
                print(f"  {status} {our_name}: ours={our_value}, theirs={their_value} (wire={wire})")
                
            except NotImplementedError:
                print(f"  ⚠️  {our_name}: transport not implemented yet")
                break
            except Exception as e:
                print(f"  ❌ {our_name}: ERROR - {e}")

    print("\n" + "=" * 60)
    print(f"Total: {len(results)} params tested")
    print(f"Matches: {len(results) - len(mismatches)}")
    print(f"Mismatches: {len(mismatches)}")
    
    if mismatches:
        print("\n--- MISMATCHES ---")
        for m in mismatches:
            print(f"  {m['block']}.{m['param']}: ours={m['ours']}, theirs={m['theirs']} (wire={m['wire']})")
            print(f"    → Likely cause: different decode algorithm for wire value {m['wire']}")

    # Write results to JSON for later analysis
    output_path = Path(__file__).parent / "cross_server_results.json"
    with open(output_path, "w") as f:
        json.dump({"channel": CHANNEL, "results": results, "mismatches": mismatches}, f, indent=2)
    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
