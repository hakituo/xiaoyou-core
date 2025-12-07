import json
import os
import glob
import matplotlib.pyplot as plt
import numpy as np

def load_results(results_dir):
    """Load all *.json files."""
    pattern = os.path.join(results_dir, "*.json")
    files = glob.glob(pattern)
    
    data_list = []
    print(f"Found {len(files)} result files in {results_dir}")
    
    for f in files:
        try:
            with open(f, 'r') as fd:
                data = json.load(fd)
                # Create a label like "xy_core (mock)"
                label = f"{data.get('mode', 'unknown')} ({data.get('workload', 'unknown')})"
                data['label'] = label
                data_list.append(data)
                print(f"  Loaded: {label} from {os.path.basename(f)}")
        except Exception as e:
            print(f"Error loading {f}: {e}")
            
    return data_list

def plot_exp1_concurrency(data_list, output_dir):
    """Plot RPS vs Concurrency for Exp 1."""
    if not any('exp1' in d['results'] for d in data_list):
        return

    plt.figure(figsize=(10, 6))
    
    for d in data_list:
        res = d['results'].get('exp1')
        if not res: continue
        
        # Sort by concurrency
        res.sort(key=lambda x: x['concurrency'])
        x = [r['concurrency'] for r in res]
        y = [r['rps'] for r in res]
        
        plt.plot(x, y, marker='o', label=d['label'])
        
    plt.xlabel('Concurrency (Tasks)')
    plt.ylabel('Throughput (RPS)')
    plt.title('Experiment 1: System Throughput vs Concurrency')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    
    out_path = os.path.join(output_dir, 'exp1_concurrency_rps.pdf')
    plt.savefig(out_path)
    print(f"Saved {out_path}")
    plt.close()

def plot_exp2_blocking(data_list, output_dir):
    """Plot Max Blocking Lag for Exp 2."""
    if not any('exp2' in d['results'] for d in data_list):
        return

    labels = []
    max_lags = []
    avg_lags = []
    
    for d in data_list:
        res = d['results'].get('exp2')
        if not res: continue
        
        labels.append(d['label'])
        max_lags.append(res.get('max_lag', 0) * 1000) # ms
        avg_lags.append(res.get('avg_lag', 0) * 1000) # ms
        
    if not labels: return

    x = np.arange(len(labels))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(10, 6))
    rects1 = ax.bar(x - width/2, max_lags, width, label='Max Lag')
    rects2 = ax.bar(x + width/2, avg_lags, width, label='Avg Lag')
    
    ax.set_ylabel('Latency (ms)')
    ax.set_title('Experiment 2: Main Thread Blocking Latency')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.legend()
    
    ax.bar_label(rects1, padding=3, fmt='%.1f')
    ax.bar_label(rects2, padding=3, fmt='%.1f')
    
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'exp2_blocking_latency.pdf')
    plt.savefig(out_path)
    print(f"Saved {out_path}")
    plt.close()

def plot_exp3_distribution(data_list, output_dir):
    """Plot Latency Distribution for Exp 3."""
    if not any('exp3' in d['results'] for d in data_list):
        return
        
    plt.figure(figsize=(10, 6))
    
    # Use boxplot for distribution comparison
    plot_data = []
    labels = []
    
    for d in data_list:
        res = d['results'].get('exp3')
        if not res: continue
        
        # Convert to ms
        latencies_ms = [l * 1000 for l in res]
        plot_data.append(latencies_ms)
        labels.append(d['label'])
        
    if not plot_data: return
    
    plt.boxplot(plot_data, tick_labels=labels)
    plt.ylabel('Task Latency (ms)')
    plt.title('Experiment 3: Task Latency Distribution')
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    plt.xticks(rotation=45, ha='right')
    
    plt.tight_layout()
    out_path = os.path.join(output_dir, 'exp3_latency_dist.pdf')
    plt.savefig(out_path)
    print(f"Saved {out_path}")
    plt.close()

def plot_exp4_stability(data_list, output_dir):
    """Plot Stability (Completed vs Errors) for Exp 4."""
    if not any('exp4' in d['results'] for d in data_list):
        return

    labels = []
    completed = []
    errors = []
    throughput = []

    for d in data_list:
        res = d['results'].get('exp4')
        if not res: continue
        
        labels.append(d['label'])
        c = res.get('completed', 0)
        e = res.get('errors', 0)
        dur = res.get('duration', 30)
        
        completed.append(c)
        errors.append(e)
        throughput.append(c / dur if dur > 0 else 0)

    if not labels: return

    x = np.arange(len(labels))
    width = 0.25

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Plot 1: Total Tasks & Errors
    rects1 = ax1.bar(x - width/2, completed, width, label='Completed', color='green', alpha=0.7)
    rects2 = ax1.bar(x + width/2, errors, width, label='Errors', color='red', alpha=0.7)
    
    ax1.set_ylabel('Count')
    ax1.set_title('Total Tasks Completed & Errors (Stability Test)')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=45, ha='right')
    ax1.legend()
    ax1.bar_label(rects1, padding=3)
    ax1.bar_label(rects2, padding=3)

    # Plot 2: Throughput
    rects3 = ax2.bar(x, throughput, width*1.5, label='Throughput', color='blue', alpha=0.6)
    ax2.set_ylabel('Tasks / Second')
    ax2.set_title('System Stability Throughput')
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=45, ha='right')
    ax2.bar_label(rects3, padding=3, fmt='%.2f')

    plt.tight_layout()
    out_path = os.path.join(output_dir, 'exp4_stability.pdf')
    plt.savefig(out_path)
    print(f"Saved {out_path}")
    plt.close()

def main():
    # Setup paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Results are in mvp_core/experiment_results
    results_dir = os.path.join(script_dir, "..", "experiment_results")
    # Output charts to mvp_core/experiments/experiment_results
    output_dir = os.path.join(script_dir, "experiment_results")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Reading results from: {results_dir}")
    print(f"Saving charts to: {output_dir}")

    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Load data
    data_list = load_results(results_dir)
    
    if not data_list:
        print("No data found. Please run comprehensive_experiment.py first.")
        return
        
    # Generate Plots
    plot_exp1_concurrency(data_list, output_dir)
    plot_exp2_blocking(data_list, output_dir)
    plot_exp3_distribution(data_list, output_dir)
    plot_exp4_stability(data_list, output_dir)
    
if __name__ == "__main__":
    main()
