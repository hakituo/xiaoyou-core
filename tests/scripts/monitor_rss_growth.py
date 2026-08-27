"""RSS 增长监控脚本

每 30 秒记录一次目标进程的 RSS、线程数、private bytes，
用于定位内存泄漏的增长曲线。

用法：
    python monitor_rss_growth.py [--pid 12345] [--interval 30] [--output rss_log.csv]

如果不指定 --pid，会自动找监听 8000 端口的 python 进程。
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

try:
    import psutil
except ImportError:
    print("[ERROR] 需要安装 psutil: pip install psutil")
    sys.exit(1)


def find_target_pid(port: int = 8000) -> int:
    """找监听指定端口的 Python 进程"""
    for conn in psutil.net_connections(kind="tcp"):
        if conn.laddr.port == port and conn.status == "LISTEN":
            try:
                p = psutil.Process(conn.pid)
                if "python" in p.name().lower():
                    return conn.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return -1


def get_rss_mb(pid: int) -> dict:
    """获取进程的内存和线程信息"""
    try:
        p = psutil.Process(pid)
        mem_info = p.memory_info()
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pid": pid,
            "rss_mb": round(mem_info.rss / 1024 / 1024, 1),
            "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
            "private_mb": round(mem_info.private / 1024 / 1024, 1) if hasattr(mem_info, "private") else 0,
            "threads": p.num_threads(),
            "handles": p.num_handles() if hasattr(p, "num_handles") else 0,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pid": pid, "rss_mb": -1}


def main():
    parser = argparse.ArgumentParser(description="RSS 增长监控")
    parser.add_argument("--pid", type=int, default=-1, help="目标进程 PID（默认自动找 8000 端口）")
    parser.add_argument("--interval", type=int, default=30, help="采样间隔（秒）")
    parser.add_argument("--output", type=str, default="rss_log.csv", help="输出 CSV 文件")
    parser.add_argument("--port", type=int, default=8000, help="查找端口（pid=-1 时使用）")
    args = parser.parse_args()

    pid = args.pid
    if pid == -1:
        pid = find_target_pid(args.port)
        if pid == -1:
            print(f"[ERROR] 找不到监听端口 {args.port} 的 Python 进程")
            sys.exit(1)

    print(f"[INFO] 监控 PID={pid}, 间隔={args.interval}s, 输出={args.output}")
    print(f"{'时间':<22} {'RSS(MB)':>10} {'VMS(MB)':>10} {'Priv(MB)':>10} {'线程':>6} {'句柄':>8} {'增长(MB)':>10}")
    print("-" * 82)

    baseline_rss = None
    last_rss = None
    fieldnames = ["timestamp", "pid", "rss_mb", "vms_mb", "private_mb", "threads", "handles"]

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        while True:
            info = get_rss_mb(pid)
            if info["rss_mb"] == -1:
                print(f"[{info['timestamp']}] 进程 {pid} 已退出")
                break

            if baseline_rss is None:
                baseline_rss = info["rss_mb"]
            growth = info["rss_mb"] - baseline_rss
            delta = info["rss_mb"] - last_rss if last_rss is not None else 0

            print(
                f"{info['timestamp']:<22} {info['rss_mb']:>10.1f} {info['vms_mb']:>10.1f} "
                f"{info['private_mb']:>10.1f} {info['threads']:>6} {info['handles']:>8} {growth:>+10.1f}"
                + (f"  ({delta:+.1f})" if delta != 0 else "")
            )

            writer.writerow(info)
            f.flush()

            last_rss = info["rss_mb"]
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
