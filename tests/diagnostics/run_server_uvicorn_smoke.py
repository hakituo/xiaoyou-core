import os
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

import requests


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _start_backend() -> Tuple[subprocess.Popen, List[str]]:
    root = _repo_root()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines: List[str] = []

    def _reader():
        if not proc.stdout:
            return
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            print(line, flush=True)

    threading.Thread(target=_reader, daemon=True).start()
    return proc, lines


def _probe_port(port: int, timeout_s: float = 1.0) -> bool:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout_s)
        return resp.status_code == 200
    except Exception:
        return False


def _wait_for_backend(max_wait_s: float = 60.0) -> Optional[int]:
    start = time.time()
    while (time.time() - start) < max_wait_s:
        for port in range(8000, 8051):
            if _probe_port(port):
                return port
        time.sleep(0.5)
    return None


def _count_keywords(lines: List[str], start: int, end: int, keywords: List[str]) -> int:
    count = 0
    for line in lines[start:end]:
        for kw in keywords:
            if kw in line:
                count += 1
                break
    return count


def main():
    proc, lines = _start_backend()

    try:
        port = _wait_for_backend(max_wait_s=120.0)
        if not port:
            print("Backend did not become healthy within timeout.", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            sys.exit(1)

        startup_log_end = len(lines)

        conv_id = f"test_uvicorn_user_{int(time.time())}"
        greeting_url = f"http://127.0.0.1:{port}/api/v1/greeting"
        message_url = f"http://127.0.0.1:{port}/api/v1/message"

        seed_name = "E2E001"
        try:
            seed_payload = {
                "content": f"我叫{seed_name}",
                "conversation_id": conv_id,
                "stream": False,
            }
            seed_resp = requests.post(message_url, json=seed_payload, timeout=120)
            print(f"Seed Profile Status: {seed_resp.status_code}", flush=True)
        except Exception as e:
            print(f"Seed profile request failed: {e}", flush=True)
            sys.exit(3)

        print(f"Fetching greeting: {greeting_url}", flush=True)
        try:
            resp = requests.get(
                greeting_url, params={"conversation_id": conv_id}, timeout=60
            )
            print(f"Greeting Status: {resp.status_code}", flush=True)
            try:
                greeting_json = resp.json()
                print(f"Greeting JSON: {greeting_json}", flush=True)
                greeting_text = str(greeting_json.get("greeting", ""))
                if "Leslie" in greeting_text:
                    print(f"Greeting contains forbidden default name: {greeting_text}", flush=True)
                    sys.exit(4)
            except Exception:
                print(f"Greeting Text: {resp.text[:2000]}", flush=True)
        except Exception as e:
            print(f"Greeting request failed: {e}", flush=True)
            sys.exit(2)

        try:
            resp2 = requests.get(greeting_url, timeout=60)
            print(f"Greeting(No CID) Status: {resp2.status_code}", flush=True)
            gj2 = resp2.json()
            print(f"Greeting(No CID) JSON: {gj2}", flush=True)
            gt2 = str(gj2.get("greeting", ""))
            if "Leslie" in gt2:
                print(f"Greeting(No CID) contains forbidden default name: {gt2}", flush=True)
                sys.exit(5)
        except Exception as e:
            print(f"Greeting(No CID) request failed: {e}", flush=True)
            sys.exit(6)

        last_response_text = ""
        for i in range(10):
            if i == 0:
                content = "第1轮：你好，这是一个十轮对话压测。请简单自我介绍一句。"
            else:
                content = (
                    f"第{i + 1}轮：请用一句话复述你上一轮的回答要点：{last_response_text[:200]}"
                )

            payload = {
                "content": content,
                "conversation_id": conv_id,
                "stream": False,
            }

            print(f"Sending request #{i + 1} to {message_url}", flush=True)
            try:
                resp = requests.post(message_url, json=payload, timeout=600)
                print(f"Response #{i + 1} Status: {resp.status_code}", flush=True)
                try:
                    data = resp.json()
                    print(f"Response #{i + 1} JSON: {data}", flush=True)
                    if resp.status_code != 200 or data.get("status") != "success":
                        print("Unexpected response structure.", flush=True)
                        sys.exit(20 + i)
                    last_response_text = str(data.get("response", ""))
                except Exception:
                    print(f"Response #{i + 1} Text: {resp.text[:2000]}", flush=True)
                    sys.exit(40 + i)
            except Exception as e:
                print(f"Request #{i + 1} failed: {e}", flush=True)
                sys.exit(60 + i)
            finally:
                time.sleep(0.8)

        after_request_log_end = len(lines)

        startup_model_keywords = [
            "Initializing GPU Worker (loading model)...",
            "正在加载文本模型:",
            "检测到GGUF模型，使用llama_cpp加载...",
            "Loading Llama model (Python)",
            "LocalLLMAdapter: Loading model...",
        ]
        error_keywords = [
            "CUDA error",
            "ggml-cuda.cu",
            "ConnectionResetError",
            "invalid vector subscript",
            "access violation",
        ]

        startup_model_loads = _count_keywords(
            lines, 0, startup_log_end, startup_model_keywords
        )
        after_request_model_loads = _count_keywords(
            lines, startup_log_end, after_request_log_end, startup_model_keywords
        )
        error_hits = _count_keywords(lines, 0, after_request_log_end, error_keywords)

        print(
            f"Model load keywords: startup={startup_model_loads}, after_request={after_request_model_loads}",
            flush=True,
        )
        print(f"Error keywords: total={error_hits}", flush=True)
        if error_hits > 0:
            sys.exit(4)
        sys.exit(0)

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
