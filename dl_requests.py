#!/usr/bin/env python3
"""Download all images from online-media.txt using requests + proxy."""
import os, re, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
INPUT_FILE = "D:/AI/xiaoyou-core/online-media-tmp.txt"
OUT_DIR = "D:/Air_Plane/image1"
FAIL_FILE = "D:/AI/xiaoyou-core/download_failed.txt"
MAX_WORKERS = 10

os.makedirs(OUT_DIR, exist_ok=True)
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    urls = [l.strip() for l in f if l.strip().startswith("http")]
total = len(urls)
open(FAIL_FILE, "w").close()
print(f"[{time.strftime('%H:%M:%S')}] Starting: {total} images, {MAX_WORKERS} threads", flush=True)

def dl(args):
    idx, url = args
    m = re.search(r"/media/([^?]+)", url)
    if not m:
        return (idx, False)
    mid = m.group(1)
    path = os.path.join(OUT_DIR, f"{mid}.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return (idx, True)
    try:
        r = requests.get(url, proxies=PROXY, headers=HEADERS, timeout=60)
        if r.status_code == 200 and len(r.content) > 0:
            with open(path, "wb") as f:
                f.write(r.content)
            return (idx, True)
        else:
            with open(FAIL_FILE, "a") as f:
                f.write(url + "\n")
            return (idx, False)
    except Exception:
        with open(FAIL_FILE, "a") as f:
            f.write(url + "\n")
        return (idx, False)

ok = 0
fail = 0
t0 = time.time()
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    for fut in as_completed({ex.submit(dl, (i, u)): i for i, u in enumerate(urls)}):
        _, success = fut.result()
        if success:
            ok += 1
        else:
            fail += 1
        done = ok + fail
        if done % 50 == 0 or done == total:
            el = time.time() - t0
            rate = done / el if el > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(f"[{time.strftime('%H:%M:%S')}] {done}/{total} | OK:{ok} FAIL:{fail} | {rate:.1f}/s ETA:{eta:.0f}s", flush=True)

el = time.time() - t0
print(f"\n[{time.strftime('%H:%M:%S')}] === Complete ===", flush=True)
print(f"Downloaded: {ok}/{total} | Failed: {fail} | Time: {el:.1f}s", flush=True)
if fail > 0:
    print(f"Failed URLs: {FAIL_FILE}", flush=True)
