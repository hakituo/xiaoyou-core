import json
import os

data_path = r"d:\AI\xiaoyou-core\paper\experiment\experiment_results\data\comprehensive_results.json"

with open(data_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=== Experiment Isolation ===")
iso = data['experiments']['experiment_isolation']['summary']
print(f"Sync Latency: {iso['sync_short_latency']}")
print(f"Async Latency: {iso['async_short_latency']}")
improvement = (iso['sync_short_latency'] - iso['async_short_latency']) / iso['sync_short_latency'] * 100
print(f"Improvement: {improvement:.2f}%")

print("\n=== Experiment 1 (Concurrency) ===")
exp1 = data['experiments']['experiment_1']
for load_type, res in exp1.items():
    if 'aggregates' in res:
        print(f"Load: {load_type}")
        print(f"Improvement: {res['aggregates']['improvement_pct']:.2f}%")

print("\n=== Paper Claims ===")
print("Latency reduction: 57.28% - 84.09%")
print("Concurrency improvement: 134.06% - 528.61%")
