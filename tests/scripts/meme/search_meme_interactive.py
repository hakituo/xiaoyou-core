"""表情包语义检索交互式测试脚本

输入自然语言，显示 top-5 匹配候选（含相似度、caption、图片路径），
可选打开图片查看实际效果。

用法：
    d:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\meme\\search_meme_interactive.py

命令：
    直接输入文字 → 搜索
    :q / :quit / exit → 退出
    :open N → 打开第 N 个候选的图片（用系统默认查看器）
    :desc N → 显示第 N 个候选的完整 caption
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MEMES_ROOT = PROJECT_ROOT / "data" / "memes"
INDEX_DIR = MEMES_ROOT / "_index"
DESCRIPTIONS_PATH = INDEX_DIR / "descriptions.json"
SEMANTIC_METADATA_PATH = INDEX_DIR / "semantic_metadata.json"


def _load_captions() -> dict[str, dict]:
    """合并 descriptions.json 和 semantic_metadata.json，返回 path -> caption 信息。"""
    result: dict[str, dict] = {}

    # descriptions.json（VL 生成，优先）
    if DESCRIPTIONS_PATH.is_file():
        try:
            with open(DESCRIPTIONS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("items", []):
                p = item.get("path")
                if p:
                    result[p] = {
                        "caption": item.get("caption", ""),
                        "tags": item.get("tags", []),
                        "text": item.get("text", ""),
                        "source": "descriptions",
                    }
        except Exception as e:
            print(f"⚠ 读取 descriptions.json 失败: {e}")

    # semantic_metadata.json（增强版自带，补充不存在的）
    if SEMANTIC_METADATA_PATH.is_file():
        try:
            with open(SEMANTIC_METADATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items") or data
            if isinstance(items, dict):
                items = [{"path": k, "caption": v} for k, v in items.items()]
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                p = item.get("path")
                if p and p not in result:
                    cap = item.get("caption") or item.get("description") or ""
                    tags = item.get("tags") or []
                    if cap:
                        result[p] = {
                            "caption": cap,
                            "tags": tags if isinstance(tags, list) else [],
                            "text": item.get("text", ""),
                            "source": "semantic_metadata",
                        }
        except Exception as e:
            print(f"⚠ 读取 semantic_metadata.json 失败: {e}")

    return result


def _search_topk(query: str, top_k: int = 5) -> list[tuple[float, str]]:
    """底层检索：返回 [(similarity, rel_path), ...] top-K 列表。"""
    # 导入模块本身，避免 from import 捕获 None 值（_load_index 后模块级变量才更新）
    from clients.bots.qq.meme_search import _load_index, _encode_query
    import clients.bots.qq.meme_search as ms

    if not _load_index():
        return []
    query_vec = _encode_query(query)
    if query_vec is None:
        return []
    sims = ms._vectors @ query_vec
    top_indices = np.argsort(sims)[::-1][:top_k]
    return [(float(sims[i]), ms._paths[i]) for i in top_indices]


def _format_caption(info: dict, max_len: int = 80) -> str:
    """格式化 caption 显示，截断过长内容。"""
    cap = info.get("caption", "")
    if len(cap) > max_len:
        cap = cap[:max_len] + "…"
    tags = info.get("tags", [])
    tag_str = "、".join(tags[:4]) if tags else ""
    text = info.get("text", "")
    parts = [cap]
    if tag_str:
        parts.append(f"[{tag_str}]")
    if text and text != "无":
        parts.append(f"文字:{text}")
    return " ".join(parts)


def _open_image(rel_path: str) -> None:
    """用系统默认查看器打开图片。"""
    full = MEMES_ROOT / rel_path
    if not full.is_file():
        print(f"❌ 图片不存在: {full}")
        return
    print(f"📂 打开: {full}")
    os.startfile(str(full))


def main():
    print("=" * 70)
    print("表情包语义检索测试")
    print("=" * 70)
    print("输入自然语言描述你想找的表情包，比如：")
    print("  - 被气到想打人")
    print("  - 慵懒地喝茶享受生活")
    print("  - 群聊被吓到")
    print("  - 认输服了")
    print()
    print("命令：")
    print("  :q / :quit / exit → 退出")
    print("  :open N → 打开第 N 个候选图片")
    print("  :desc N → 显示第 N 个候选的完整 caption")
    print("=" * 70)

    # 预加载索引
    print("\n加载索引中...", end=" ")
    from clients.bots.qq.meme_search import _load_index
    if not _load_index():
        print("❌ 索引加载失败，请先运行 build_meme_vector_index.py")
        return
    print("完成")

    # 预加载 captions
    captions = _load_captions()
    print(f"已加载 {len(captions)} 条 caption\n")

    last_results: list[tuple[float, str]] = []

    while True:
        try:
            query = input("\n🔍 搜索> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break

        if not query:
            continue

        # 命令处理
        if query in (":q", ":quit", "exit", "quit"):
            print("再见")
            break
        if query.startswith(":open ") or query.startswith(":o "):
            try:
                n = int(query.split()[-1]) - 1
                if 0 <= n < len(last_results):
                    _open_image(last_results[n][1])
                else:
                    print(f"❌ 序号超出范围（1-{len(last_results)}）")
            except (ValueError, IndexError):
                print("❌ 用法：:open N（N 为候选序号）")
            continue
        if query.startswith(":desc ") or query.startswith(":d "):
            try:
                n = int(query.split()[-1]) - 1
                if 0 <= n < len(last_results):
                    sim, rel = last_results[n]
                    info = captions.get(rel, {})
                    print(f"\n📋 [{n+1}] {rel}  (sim={sim:.3f})")
                    print(f"   caption: {info.get('caption', '(无)')}")
                    print(f"   tags: {info.get('tags', [])}")
                    print(f"   text: {info.get('text', '')}")
                    print(f"   source: {info.get('source', '?')}")
                else:
                    print(f"❌ 序号超出范围（1-{len(last_results)}）")
            except (ValueError, IndexError):
                print("❌ 用法：:desc N（N 为候选序号）")
            continue
        if query == ":help" or query == ":h":
            print("命令：:q 退出 | :open N 打开图 | :desc N 看完整描述")
            continue

        # 搜索
        results = _search_topk(query, top_k=5)
        last_results = results

        if not results:
            print("❌ 未找到匹配（索引为空或模型加载失败）")
            continue

        print(f"\n查询: {query!r}  →  top-{len(results)} 候选:")
        print("-" * 70)
        for i, (sim, rel) in enumerate(results, 1):
            info = captions.get(rel, {})
            cap_str = _format_caption(info) if info else "(无 caption)"
            # 标记文件是否真实存在
            exists = "✓" if (MEMES_ROOT / rel).is_file() else "✗"
            print(f"  [{i}] sim={sim:.3f} {exists} {rel}")
            print(f"      {cap_str}")
        print("-" * 70)
        print(f"输入 :open N 打开第 N 张图，:desc N 看完整描述")


if __name__ == "__main__":
    main()
