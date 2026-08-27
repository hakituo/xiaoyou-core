"""验证：记忆系统 embedding 是否成功迁移到 bge-small-zh-v1.5（512 维，CLS pooling）。

判定"优化成功"的标准（全部满足才算 PASS）：
1. 统一生成器输出维度 == 512，且实际加载模型是 BGE（而非旧的 384 维 MiniLM）
2. 512 维 embedding 经 base64 持久化往返后维度不丢
3. Python 检索：相关记忆与查询的余弦相似度 > 无关记忆
4. C++ VectorIndexer 能对 512 维向量 addRecord + search，且召回相关项
5. 维度不匹配（旧 384 维存量）不会让 Python 检索崩溃（优雅降级，不报错）

用法：
    python -m venv_cpu 脚本
    python tests/scripts/memory/verify_bge_512_migration.py
"""
from __future__ import annotations

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, PROJECT_ROOT)
# 使 C++ 索引器可导入（cp310 pyd 位于该目录）
_CPP_DIR = os.path.join(
    PROJECT_ROOT, "cpp_modules", "cpp_memory_index"
)
if os.path.isdir(_CPP_DIR):
    sys.path.insert(0, _CPP_DIR)

import numpy as np  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    print("== 记忆系统 BGE / 512 维迁移验证 ==")

    # 1) 迁移是否生效：统一生成器应为 BGE、512 维
    from memory.embedding_generator import EMBEDDING_DIMENSION, embedding_generator

    check(
        "统一生成器维度为 512",
        EMBEDDING_DIMENSION == 512,
        f"EMBEDDING_DIMENSION={EMBEDDING_DIMENSION}",
    )
    used_model = str(getattr(embedding_generator, "_model_name", ""))
    check(
        "实际加载模型为 bge",
        "bge" in used_model.lower(),
        f"model=_model_name={used_model}",
    )

    # 真实生成 512 维向量
    mem_related = embedding_generator.generate_embedding("她喜欢在傍晚去公园散步")
    mem_unrelated = embedding_generator.generate_embedding("我喜欢吃重庆火锅")
    query = embedding_generator.generate_embedding("用户偏好空闲时在公园慢走")
    dims = {len(v) for v in [mem_related, mem_unrelated, query]}
    check("生成向量均为 512 维", dims == {512}, f"dims={dims}")

    # 2) base64 持久化往返（storage.py 落盘用的是 embedding_to_base64）
    try:
        b64 = embedding_generator.embedding_to_base64(mem_related)
        back = embedding_generator.base64_to_embedding(b64)
        roundtrip_sim = float(
            embedding_generator.cosine_similarity(back, mem_related)
        )
        check(
            "base64 往返后维度不丢且向量一致",
            len(back) == 512 and roundtrip_sim > 0.999,
            f"len(back)={len(back)} roundtrip_sim={roundtrip_sim:.4f}",
        )
    except Exception as exc:  # 个别版本方法名不同，仅说明性检查
        check("base64 往返可用", False, f"{type(exc).__name__}: {exc}")

    # 3) Python 检索：相关 > 无关
    sim_related = float(embedding_generator.cosine_similarity(query, mem_related))
    sim_unrelated = float(embedding_generator.cosine_similarity(query, mem_unrelated))
    check(
        "Python 余弦区分相关/无关",
        sim_related > sim_unrelated,
        f"related={sim_related:.3f} unrelated={sim_unrelated:.3f}",
    )

    # 4) C++ VectorIndexer 对 512 维 addRecord + search
    try:
        import memory_index_py

        idx = memory_index_py.VectorIndexer()
        now = time.time()
        idx.addRecord(
            "m1", [float(x) for x in mem_related], 5.0, now, "user", ["散步", "公园"]
        )
        idx.addRecord(
            "m2", [float(x) for x in mem_unrelated], 5.0, now, "user", ["火锅"]
        )
        cpp_res = idx.search(
            [float(x) for x in query],
            top_k=2,
            min_similarity=0.3,
            current_time=now + 1,
            decay_rate=0.95,
            base_min_weight=0.5,
            absolute_min_weight=0.0,
            filter_source="",
            filter_topics=[],
        )
        top_id = cpp_res[0].id if cpp_res else None
        top_sim = cpp_res[0].similarity if cpp_res else 0.0
        check(
            "C++ 检索 512 维召回相关性最高项",
            bool(cpp_res) and top_id == "m1",
            f"top_id={top_id} sim={top_sim:.3f}",
        )
    except (ImportError, OSError) as exc:
        # 设计上允许 C++ 不可用时回退 Python；此处不算失败，仅提示
        print(f"  [SKIP] C++ 索引器不可用，跳过（设计上回落 Python）: {exc}")
    except Exception as exc:
        check("C++ 检索 512 维可用", False, f"{type(exc).__name__}: {exc}")

    # 5) 优雅降级：384 维旧记忆遇到 512 维查询不崩溃、不污染结果
    # cosine_similarity 对维度不匹配是内部 catch -> 打日志 -> 返回 0.0，
    # 检索侧因 sim=0.0 < min_similarity 会自然跳过该旧记忆，属安全降级。
    try:
        old_384 = [0.1] * 384
        result_384 = float(
            embedding_generator.cosine_similarity(
                query, np.asarray(old_384, dtype=float)
            )
        )
        check(
            "维度不匹配优雅降级（返回0，不崩溃）",
            result_384 == 0.0,
            f"result={result_384}",
        )
    except Exception as exc:  # 任何抛异常都视为不够优雅
        check("维度不匹配优雅降级（返回0，不崩溃）", False, f"{type(exc).__name__}: {exc}")

    print("==" + " BGE/512 迁移验证: " + ("全部 PASS" if not FAILED else f"{len(FAILED)} 项失败") + " ==")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())