#!/usr/bin/env python3
"""Classify round-trip test failures into actionable categories.

Reads roundtrip_results.json and categorizes each failure.
"""

import json
from pathlib import Path
from collections import defaultdict

RESULTS_PATH = Path(__file__).parent / "roundtrip_results.json"

with open(RESULTS_PATH) as f:
    results = json.load(f)

errors = results.get("errors", [])
print(f"Total failures: {len(errors)}")
print()

categories = defaultdict(list)

for err in errors:
    block = err.get("block", "?")
    param = err.get("param", "?")
    sent = err.get("sent")
    got = err.get("got")
    raw = err.get("raw")
    error_msg = err.get("error")

    label = f"{block}/{param}"

    if error_msg:
        categories["error_msg"].append((label, error_msg))
        continue

    if sent is None or got is None:
        categories["unknown"].append((label, err))
        continue

    # Pattern: got = 0 or got = -min (raw=0) -> type-specific inactive
    if raw == 0 and got != sent:
        categories["type_specific_inactive"].append((label, sent, got))
        continue

    # Pattern: raw = 65534 (max) -> value saturated/clamped
    if raw == 65534 and got != sent:
        categories["saturated_max"].append((label, sent, got))
        continue

    # Pattern: got ≈ 2*sent -> max is half of actual
    if sent != 0 and abs(got / sent - 2.0) < 0.1:
        categories["max_half"].append((label, sent, got))
        continue

    # Pattern: got ≈ sent/2 -> max is double actual
    if sent != 0 and abs(got / sent - 0.5) < 0.1:
        categories["max_double"].append((label, sent, got))
        continue

    # Pattern: frequency log scale mismatch (sent=1000, got=223 or got=7071)
    if sent == 1000.0 and (200 < got < 250 or 6000 < got < 8000):
        categories["freq_log_mismatch"].append((label, sent, got))
        continue

    # Pattern: small enum-like values (raw < 10, got=0)
    if raw is not None and raw < 10 and got == 0:
        categories["likely_enum"].append((label, sent, got, raw))
        continue

    # Everything else
    categories["other"].append((label, sent, got, raw))


# Print summary
print("=" * 60)
print("FAILURE CLASSIFICATION")
print("=" * 60)
print()

for cat, items in sorted(categories.items(), key=lambda x: -len(x[1])):
    print(f"### {cat} ({len(items)} failures)")
    print()
    
    if cat == "type_specific_inactive":
        print("  SET had no effect (raw=0). Param is inactive for current type.")
        print("  ACTION: Skip in test (type-specific filtering)")
        for label, sent, got in items[:5]:
            print(f"    {label}: sent={sent}, got={got}")
        if len(items) > 5:
            print(f"    ... and {len(items)-5} more")
    
    elif cat == "saturated_max":
        print("  Value hit max (raw=65534). Either type-specific inactive or max too low.")
        print("  ACTION: Check if param is active. If yes, fix max in all_params.json")
        for label, sent, got in items[:5]:
            print(f"    {label}: sent={sent}, got={got}")
        if len(items) > 5:
            print(f"    ... and {len(items)-5} more")
    
    elif cat == "max_half":
        print("  Readback is ~2x sent. all_params.json max is likely half the real max.")
        print("  ACTION: Double the max in all_params.json")
        for label, sent, got in items[:10]:
            print(f"    {label}: sent={sent}, got={got} (real_max ≈ {got*2:.0f}?)")
        if len(items) > 10:
            print(f"    ... and {len(items)-10} more")
    
    elif cat == "max_double":
        print("  Readback is ~0.5x sent. all_params.json max is likely double the real max.")
        print("  ACTION: Halve the max in all_params.json")
        for label, sent, got in items[:10]:
            print(f"    {label}: sent={sent}, got={got}")
        if len(items) > 10:
            print(f"    ... and {len(items)-10} more")
    
    elif cat == "freq_log_mismatch":
        print("  Frequency param with wrong log scale max.")
        print("  ACTION: Fix max_freq in all_params.json (likely 10000 vs 20000)")
        for label, sent, got in items[:10]:
            print(f"    {label}: sent={sent}, got={got}")
    
    elif cat == "likely_enum":
        print("  Small raw value, likely an enum param misclassified as continuous.")
        print("  ACTION: Change type to 'enum' in all_params.json")
        for label, sent, got, raw in items[:10]:
            print(f"    {label}: sent={sent}, got={got}, raw={raw}")
    
    elif cat == "error_msg":
        print("  SET/GET returned an error.")
        for label, msg in items[:5]:
            print(f"    {label}: {msg}")
    
    else:
        print("  Unclassified failures (need manual investigation)")
        for item in items[:10]:
            print(f"    {item}")
        if len(items) > 10:
            print(f"    ... and {len(items)-10} more")
    
    print()

# Summary table
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"{'Category':<25} {'Count':>6} {'Action'}")
print("-" * 60)
for cat, items in sorted(categories.items(), key=lambda x: -len(x[1])):
    actions = {
        "type_specific_inactive": "Skip in test",
        "saturated_max": "Fix max or skip",
        "max_half": "Fix all_params.json",
        "max_double": "Fix all_params.json",
        "freq_log_mismatch": "Fix all_params.json",
        "likely_enum": "Fix type in all_params.json",
        "error_msg": "Investigate",
        "other": "Manual investigation",
        "unknown": "Investigate",
    }
    print(f"{cat:<25} {len(items):>6} {actions.get(cat, '?')}")
