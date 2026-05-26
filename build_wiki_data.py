#!/usr/bin/env python3
"""Parse Fractal Audio Wiki pages into structured JSON for MCP lookup.

Fetches and parses:
- Amp models: https://wiki.fractalaudio.com/wiki/index.php?title=Amp_models
- Drive block: https://wiki.fractalaudio.com/wiki/index.php?title=Drive_block

Output: fm9_wiki_models.json

Usage:
    python3 build_wiki_data.py [--fetch]  # --fetch to re-download from wiki
"""

import json
import re
import subprocess
import sys
from pathlib import Path

WIKI_BASE = "https://wiki.fractalaudio.com/wiki/index.php?title="

PAGES = {
    "amp": "Amp_models",
    "drive": "Drive_block",
}


def fetch_page(title: str, output_file: str) -> str:
    """Fetch wiki page as plain text via pandoc."""
    url = f"{WIKI_BASE}{title}"
    result = subprocess.run(
        ["pandoc", "-f", "html", "-t", "plain", url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error fetching {url}: {result.stderr}", file=sys.stderr)
        return ""
    Path(output_file).write_text(result.stdout)
    return result.stdout


def fetch_page_md(title: str, output_file: str) -> str:
    """Fetch wiki page as markdown via pandoc."""
    url = f"{WIKI_BASE}{title}"
    result = subprocess.run(
        ["pandoc", "-f", "html", "-t", "markdown", url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error fetching {url}: {result.stderr}", file=sys.stderr)
        return ""
    Path(output_file).write_text(result.stdout)
    return result.stdout


def parse_amp_models(md_text: str) -> list[dict]:
    """Parse amp models from markdown text."""
    models = []
    
    # Split by ## headings (each model is a ## section)
    sections = re.split(r'^## ', md_text, flags=re.MULTILINE)
    
    for section in sections[1:]:  # skip preamble
        lines = section.strip().split('\n')
        if not lines:
            continue
        
        # Parse heading: [MODEL NAME (based_on)]{#id .mw-headline}
        heading_line = lines[0]
        
        # Extract display text from pandoc markdown: [TEXT]{#id .mw-headline}
        matches = re.findall(r'\[([^\]]+)\]\{[^}]*\.mw-headline[^}]*\}', heading_line)
        if matches:
            heading = matches[-1]
        else:
            # Fallback: plain heading
            heading = re.sub(r'\{[^}]*\}', '', heading_line).strip('[] \n')
        
        # Extract model name and based_on
        match = re.match(r'^([^(]+?)(?:\s*\((.+)\))?\s*$', heading)
        if not match:
            continue
        
        model_name = match.group(1).strip()
        based_on = match.group(2).strip() if match.group(2) else ""
        
        # Skip TOC entries and non-model sections
        if not model_name or model_name.lower() in ('contents', 'amp models'):
            continue
        if len(model_name) > 80:
            continue
        
        # Parse body
        body = '\n'.join(lines[1:])
        
        # Extract cab info
        cab_original = ""
        cab_dynacab = ""
        cab_match = re.search(r'original:\s*(.+)', body)
        if cab_match:
            cab_original = cab_match.group(1).strip()
        dynacab_match = re.search(r'(?:matching )?DynaCab(?:\s*match)?:\s*(.+)', body)
        if dynacab_match:
            cab_dynacab = dynacab_match.group(1).strip()
        
        # Extract power tubes
        tubes = ""
        tubes_match = re.search(r'Power tubes?:\s*(.+)', body)
        if tubes_match:
            tubes = tubes_match.group(1).strip()
        
        # Extract controls (line with comma-separated control names)
        controls = ""
        # Look for a line that has multiple comma-separated words (Volume, Bass, etc.)
        for line in body.split('\n'):
            line = line.strip()
            if line and ',' in line and not line.startswith('-') and not line.startswith('#'):
                # Check if it looks like controls (short words separated by commas)
                parts = [p.strip() for p in line.split(',')]
                if all(len(p) < 30 for p in parts) and len(parts) >= 3:
                    if any(w in line for w in ['Volume', 'Bass', 'Treble', 'Gain', 'Master', 'Drive']):
                        controls = line
                        break
        
        # Extract models/variants
        variants = []
        in_models = False
        for line in body.split('\n'):
            line = line.strip()
            if line.lower().startswith('models:') or line.lower() == 'models':
                in_models = True
                continue
            if in_models:
                if line.startswith('- '):
                    variants.append(line[2:].strip())
                elif line and not line.startswith('-'):
                    in_models = False
        
        # Extract notes (numbered quotes from Cliff)
        notes = []
        for match in re.finditer(r'^\d+\.\s+"([^"]+)"', body, re.MULTILINE):
            quote = match.group(1).strip()
            if len(quote) > 20:  # skip very short fragments
                notes.append(quote)
        # Also try with escaped quotes
        for match in re.finditer(r"^\d+\.\s+[\"\\\"]+(.+?)[\"\\\"]+", body, re.MULTILINE):
            quote = match.group(1).strip()
            if len(quote) > 20 and quote not in notes:
                notes.append(quote)
        
        model = {
            "model_name": model_name,
            "based_on": based_on,
            "cab_original": cab_original,
            "cab_dynacab": cab_dynacab,
            "power_tubes": tubes,
            "controls": controls,
            "variants": variants,
            "notes": notes[:5],  # limit to 5 most relevant
        }
        
        # Only add if it looks like a real model entry
        if model_name and len(model_name) > 2:
            models.append(model)
    
    return models


def parse_drive_models(text: str) -> list[dict]:
    """Parse drive models from plain text."""
    models = []
    
    # Drive page has a simpler structure - list of models with descriptions
    # Look for patterns like "Model Name: based on Original Pedal"
    lines = text.split('\n')
    
    current_category = ""
    for line in lines:
        line = line.strip()
        
        # Category headers
        if line and line.isupper() and len(line) < 50:
            current_category = line
            continue
        
        # Model entries: "- Model Name (Original Pedal)"
        match = re.match(r'^[-•]\s*(.+?)(?:\s*\((.+?)\))?\s*$', line)
        if match and current_category:
            model_name = match.group(1).strip()
            based_on = match.group(2).strip() if match.group(2) else ""
            
            if model_name and len(model_name) < 60:
                models.append({
                    "model_name": model_name,
                    "based_on": based_on,
                    "category": current_category,
                })
    
    return models


def main():
    fetch = "--fetch" in sys.argv
    
    # Amp models
    amp_md_file = "wiki_amp_models.md"
    if fetch or not Path(amp_md_file).exists():
        print("Fetching Amp models...")
        md_text = fetch_page_md("Amp_models", amp_md_file)
    else:
        md_text = Path(amp_md_file).read_text()
    
    print("Parsing Amp models...")
    amp_models = parse_amp_models(md_text)
    print(f"  Found {len(amp_models)} amp models")
    
    # Drive models
    drive_txt_file = "wiki_drive_block_raw.txt"
    if fetch or not Path(drive_txt_file).exists():
        print("Fetching Drive block...")
        drive_text = fetch_page("Drive_block", drive_txt_file)
    else:
        drive_text = Path(drive_txt_file).read_text()
    
    print("Parsing Drive models...")
    drive_models = parse_drive_models(drive_text)
    print(f"  Found {len(drive_models)} drive models")
    
    # Output
    output = {
        "_source": "Fractal Audio Wiki (wiki.fractalaudio.com)",
        "_note": "Parameter names and model info from public wiki. For MCP lookup.",
        "amp_models": amp_models,
        "drive_models": drive_models,
    }
    
    output_file = "fm9_wiki_models.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\nWritten {output_file}")
    print(f"  Amp models: {len(amp_models)}")
    print(f"  Drive models: {len(drive_models)}")
    
    # Show sample
    if amp_models:
        print(f"\n  Sample amp: {json.dumps(amp_models[0], indent=2, ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    main()
