#!/usr/bin/env python3
"""Auto-fix all_params.json based on round-trip failure patterns.

Fixes:
1. likely_enum: params with raw < 10 and got=0 -> change type to "enum"
2. max_half: got ≈ 2*sent -> double the max
3. max_double: got ≈ 0.5*sent -> halve the max
4. freq_log_mismatch: frequency params with wrong max_freq

Usage:
    python3 tests/fix_from_failures.py [--dry-run]
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "fm9"
RESULTS_PATH = Path(__file__).parent / "roundtrip_results.json"


def main():
    dry_run = "--dry-run" in sys.argv

    with open(RESULTS_PATH) as f:
        results = json.load(f)
    with open(DATA_DIR / "all_params.json") as f:
        all_params = json.load(f)

    errors = results.get("errors", [])
    print(f"Analyzing {len(errors)} failures...")

    fixes = {"enum": 0, "max_half": 0, "max_double": 0, "freq": 0}

    for err in errors:
        block = err.get("block", "")
        param = err.get("param", "")
        sent = err.get("sent")
        got = err.get("got")
        raw = err.get("raw")

        if sent is None or got is None:
            continue

        # Find this param in all_params
        block_info = None
        for prefix, info in all_params.items():
            if info.get("block_name") == block:
                block_info = info
                break
        if not block_info:
            continue

        # Find param by display_name
        target_pid = None
        for pid_str, pinfo in block_info.get("params", {}).items():
            if pinfo.get("display_name") == param:
                target_pid = pid_str
                break
        if not target_pid:
            continue

        pinfo = block_info["params"][target_pid]
        meta = pinfo.get("meta", {})

        # Fix 1: likely_enum (raw < 10, got=0, sent > 1)
        if raw is not None and raw < 10 and got == 0.0 and sent > 1.0:
            if meta.get("type") != "enum":
                meta["type"] = "enum"
                pinfo["meta"] = meta
                fixes["enum"] += 1
                continue

        # Fix 2: max_half (got ≈ 2*sent)
        if sent != 0 and abs(got / sent - 2.0) < 0.15:
            old_max = meta.get("max", 10.0)
            meta["max"] = round(old_max * 2, 4)
            pinfo["meta"] = meta
            fixes["max_half"] += 1
            continue

        # Fix 3: max_double (got ≈ 0.5*sent)
        if sent != 0 and got != 0 and abs(got / sent - 0.5) < 0.15:
            old_max = meta.get("max", 10.0)
            meta["max"] = round(old_max / 2, 4)
            pinfo["meta"] = meta
            fixes["max_double"] += 1
            continue

        # Fix 4: freq_log_mismatch
        # sent=1000, got=7071 -> max should be 10000 (not 20000)
        # sent=1000, got=223 -> max should be 2000 (not 20000)
        if sent == 1000.0 and meta.get("max", 0) >= 20000:
            if 6000 < got < 8000:
                # got=7071 means sqrt(10000*1000) ≈ 7071 with max=10000
                # Actually: 20*10^(raw/65534*log10(max/20)) = got
                # If max=20000 and we get 7071 for sent=1000, the actual max is ~2000
                # Let's compute: we sent 1000 as raw_float, FM9 stored it
                # On readback with max=20000: 20*10^(raw/65534*log10(20000/20)) = 7071
                # This means raw/65534*3 = log10(7071/20) = 2.548 -> raw/65534 = 0.849
                # But we sent 1000.0 as raw_float -> FM9 stored raw = ?
                # If FM9 interprets 1000.0 as the actual Hz and stores log-encoded:
                # raw = 65534 * log10(1000/20) / log10(max/20)
                # With max=20000: raw = 65534 * 1.699/3.0 = 37090
                # Readback with max=20000: 20*10^(37090/65534*3) = 1000. Should work!
                # But got=7071 means something else is happening.
                # Most likely: the actual max is NOT 20000.
                # If max=10000: raw = 65534*log10(1000/20)/log10(10000/20) = 65534*1.699/2.699 = 41237
                # Readback with wrong max=20000: 20*10^(41237/65534*3) = 7071. YES!
                meta["max"] = 10000.0
                pinfo["meta"] = meta
                fixes["freq"] += 1
                continue
            elif 200 < got < 250:
                # got=223 with max=20000 means actual max is ~800 or ~2000
                # 223 ≈ sqrt(20*10000) nope...
                # If actual max=800: raw = 65534*log10(1000/20)/log10(800/20) = 65534*1.699/1.602 = 69xxx (overflow!)
                # If actual max=2000: raw = 65534*log10(1000/20)/log10(2000/20) = 65534*1.699/2.0 = 55670
                # Readback with wrong max=20000: 20*10^(55670/65534*3) = 20*10^(2.548) = 7071? No...
                # Hmm, let me think differently.
                # got=223.6 with raw=22903 (from earlier data):
                # decode with max=20000: 20*10^(22903/65534*log10(1000)) = 20*10^(22903/65534*3) = 20*10^(1.048) = 223.5 ✓
                # So raw=22903. We sent 1000.0 as raw_float.
                # FM9 received IEEE754 of 1000.0 and stored... what?
                # If FM9 treats it as normalized and max=20000: raw = 1000/20000*65534 = 3277. But raw=22903.
                # If FM9 treats it as raw_float Hz and log-encodes with max=2000:
                # raw = 65534*log10(1000/20)/log10(2000/20) = 65534*1.699/2.0 = 55670. Not 22903.
                # Actually raw=22903 with max=20000 decodes to 223.6. The issue is the SENT value.
                # We sent 1000.0 as raw_float. FM9 stored it as... 22903?
                # 22903/65534 = 0.3494. If this is log-encoded with max=20000:
                # freq = 20*10^(0.3494*log10(20000/20)) = 20*10^(0.3494*3) = 20*10^(1.048) = 223.5
                # So FM9 stored 0.3494 as the normalized log value.
                # We sent IEEE754 float of 1000.0. FM9 interpreted it as... 0.3494?
                # That doesn't make sense unless FM9 is doing log encoding on receive.
                # This is an ENCODING issue, not just a max issue.
                # Skip for now - needs Wireshark investigation.
                pass

    total_fixes = sum(fixes.values())
    print(f"\nFixes to apply:")
    for cat, count in fixes.items():
        print(f"  {cat}: {count}")
    print(f"  TOTAL: {total_fixes}")

    if not dry_run and total_fixes > 0:
        with open(DATA_DIR / "all_params.json", 'w') as f:
            json.dump(all_params, f, indent=2)
        print(f"\nSaved updated all_params.json")
    elif dry_run:
        print(f"\n[DRY RUN] Would fix {total_fixes} params")


if __name__ == "__main__":
    main()
