#!/usr/bin/env python3
import argparse
import json
import math
import os
from collections import Counter


def percentile(values, p):
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * p
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_values[low]
    frac = rank - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def fmt_ms(value):
    if value is None:
        return "n/a"
    return f"{value:.1f} ms"


def fmt_pct(value):
    if value is None:
        return "n/a"
    return f"{value * 100.0:.1f}%"


def load_metrics(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(payload)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Analyze SmartPOS AI telemetry metrics.")
    parser.add_argument(
        "--file",
        default=os.path.join("data", "ai_metrics.jsonl"),
        help="Path to ai_metrics.jsonl (default: data/ai_metrics.jsonl)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only analyze the last N rows (0 means all rows).",
    )
    args = parser.parse_args()

    rows = load_metrics(args.file)
    if args.limit and args.limit > 0:
        rows = rows[-args.limit :]

    if not rows:
        print("No AI metrics found.")
        print(f"Checked: {args.file}")
        return

    ai_rows = [r for r in rows if r.get("event") == "ai_cycle"]
    manual_rows = [r for r in rows if r.get("event") == "manual_assist"]

    if not ai_rows:
        print("No AI cycle metrics found.")
        print(f"Checked: {args.file}")
        return

    inference_ms = [float(r.get("ai_inference_ms") or 0.0) for r in ai_rows if r.get("ai_inference_ms") is not None]
    cycle_ms = [float(r.get("cycle_latency_ms") or 0.0) for r in ai_rows if r.get("cycle_latency_ms") is not None]
    fused_conf = [float(r.get("fused_confidence") or 0.0) for r in ai_rows]
    selected_changes = [r for r in ai_rows if bool(r.get("selected_changed"))]
    false_switches = [r for r in ai_rows if bool(r.get("false_switch"))]
    weight_transition_rows = [r for r in ai_rows if bool(r.get("recent_weight_transition"))]

    mode_counter = Counter(str(r.get("pipeline_mode") or "unknown") for r in ai_rows)
    decision_counter = Counter(str(r.get("decision") or "unknown") for r in ai_rows)
    manual_product_counter = Counter(str(r.get("selected_product") or "unknown") for r in manual_rows)

    fast_path_count = mode_counter.get("fast_frame", 0)
    fallback_count = mode_counter.get("fallback_detection", 0)
    frame_only_count = mode_counter.get("frame_only", 0)

    print("AI Telemetry Summary")
    print("====================")
    print(f"Rows analyzed (all events): {len(rows)}")
    print(f"AI cycles analyzed: {len(ai_rows)}")
    print(f"Manual assist events: {len(manual_rows)}")
    print(f"Source file: {args.file}")
    print()

    print("Latency")
    print(f"- AI inference p50: {fmt_ms(percentile(inference_ms, 0.50))}")
    print(f"- AI inference p95: {fmt_ms(percentile(inference_ms, 0.95))}")
    print(f"- End-to-end cycle p50: {fmt_ms(percentile(cycle_ms, 0.50))}")
    print(f"- End-to-end cycle p95: {fmt_ms(percentile(cycle_ms, 0.95))}")
    print()

    print("Pipeline Mix")
    print(f"- Fast path (fast_frame): {fast_path_count} ({fmt_pct(fast_path_count / len(ai_rows))})")
    print(f"- Fallback detection: {fallback_count} ({fmt_pct(fallback_count / len(ai_rows))})")
    print(f"- Frame-only non-fast: {frame_only_count} ({fmt_pct(frame_only_count / len(ai_rows))})")
    print()

    print("Recognition Stability")
    print(f"- Selected label changes: {len(selected_changes)} ({fmt_pct(len(selected_changes) / len(ai_rows))})")
    print(f"- False switches (no weight transition): {len(false_switches)} ({fmt_pct(len(false_switches) / len(ai_rows))})")
    print(f"- Cycles with recent weight transition: {len(weight_transition_rows)} ({fmt_pct(len(weight_transition_rows) / len(ai_rows))})")
    print(f"- Avg fused confidence: {sum(fused_conf) / len(fused_conf):.3f}" if fused_conf else "- Avg fused confidence: n/a")
    print()

    print("Manual Assist")
    assist_rate = (len(manual_rows) / len(ai_rows)) if ai_rows else None
    print(f"- Assist rate (events/AI cycles): {fmt_pct(assist_rate)}")
    if manual_product_counter:
        print("- Top assisted products:")
        for label, count in manual_product_counter.most_common(5):
            print(f"  - {label}: {count}")
    else:
        print("- Top assisted products: n/a")
    print()

    print("Decision Counts")
    for key, count in sorted(decision_counter.items()):
        print(f"- {key}: {count}")


if __name__ == "__main__":
    main()

