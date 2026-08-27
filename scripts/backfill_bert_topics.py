"""
BERT 记忆分类回填脚本

扫描所有记忆文件，对 topics 为空或 category 为 uncategorized 的记录，
使用 BERT 重新分类并更新。

用法：
    python scripts/backfill_bert_topics.py [--dry-run] [--limit 500]
"""
import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.services.data_ops.bert_analyzer import get_bert_analyzer
from core.utils.atomic_io import safe_json_load, safe_json_dump


# 需要扫描的目录
SCAN_DIRS = [
    "companion_data/user_data/memories",
    "companion_data/aveline_data/memories",
    "companion_data/dual_role/memories",
]


def find_memory_files(base_dirs: List[str]) -> List[Path]:
    """查找所有记忆 JSON 文件"""
    files = []
    for base_dir in base_dirs:
        full_path = project_root / base_dir
        if not full_path.exists():
            continue
        for json_file in full_path.rglob("*.json"):
            # 跳过非记忆文件
            if "config" in json_file.name.lower():
                continue
            files.append(json_file)
    return files


def needs_classification(record: Dict[str, Any]) -> bool:
    """判断记录是否需要分类"""
    # 跳过系统消息
    content = str(record.get("content", "")).strip()
    if not content or content.startswith("[SYSTEM_"):
        return False
    
    # 跳过太短的内容
    if len(content) < 5:
        return False
    
    # 检查 topics
    topics = record.get("topics", [])
    if not topics:
        return True
    
    # 检查 category
    category = record.get("category", "")
    if not category or category == "uncategorized":
        return True
    
    return False


def backfill_memory_file(
    file_path: Path,
    analyzer,
    dry_run: bool = False
) -> Dict[str, int]:
    """回填单个记忆文件"""
    stats = {"total": 0, "updated": 0, "skipped": 0, "errors": 0}
    
    try:
        data = safe_json_load(file_path)
        if not data:
            return stats
        
        # 处理不同的数据结构
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            # 尝试常见的键名
            for key in ["weighted_memories", "memories", "messages", "history", "items"]:
                if key in data and isinstance(data[key], list):
                    records = data[key]
                    break
            # 如果没找到，可能是单条记录
            if not records and data.get("content"):
                records = [data]
        
        if not records:
            return stats
        
        modified = False
        for record in records:
            if not isinstance(record, dict):
                continue
            
            stats["total"] += 1
            
            if not needs_classification(record):
                stats["skipped"] += 1
                continue
            
            content = str(record.get("content", "")).strip()
            if not content:
                stats["skipped"] += 1
                continue
            
            try:
                # BERT 分析
                result = analyzer.analyze(content)
                new_category = result.get("category", "uncategorized")
                new_topics = result.get("topics", [])
                confidence = result.get("confidence", 0)
                
                # 只更新置信度足够高的结果
                if confidence < 0.3 or new_category == "uncategorized":
                    stats["skipped"] += 1
                    continue
                
                # 更新记录
                old_category = record.get("category", "")
                old_topics = record.get("topics", [])
                
                if not dry_run:
                    record["category"] = new_category
                    # 合并 topics，保留原有的
                    merged_topics = list(set(old_topics + new_topics))[:5]
                    record["topics"] = merged_topics
                    
                    # 更新 metadata
                    if "metadata" not in record:
                        record["metadata"] = {}
                    record["metadata"]["bert_backfill"] = {
                        "timestamp": time.time(),
                        "old_category": old_category,
                        "new_category": new_category,
                        "confidence": confidence,
                    }
                    
                    modified = True
                
                stats["updated"] += 1
                
                # 打印更新信息
                if stats["updated"] <= 20:  # 只打印前20条
                    print(f"  [{old_category} -> {new_category}] {content[:50]}...")
                    print(f"    topics: {new_topics[:3]} (confidence: {confidence:.3f})")
                
            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  错误: {e}")
        
        # 保存修改
        if modified and not dry_run:
            safe_json_dump(data, file_path)
        
        return stats
        
    except Exception as e:
        print(f"  文件读取错误: {e}")
        stats["errors"] += 1
        return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BERT 记忆分类回填")
    parser.add_argument("--dry-run", action="store_true", help="只显示变更，不实际修改")
    parser.add_argument("--limit", type=int, default=500, help="最多处理的文件数")
    args = parser.parse_args()
    
    print("=" * 60)
    print("BERT 记忆分类回填工具")
    print("=" * 60)
    
    if args.dry_run:
        print("\n[DRY RUN 模式] 只显示变更，不实际修改文件\n")
    
    # 初始化 BERT
    print("正在初始化 BERT 分析器...")
    analyzer = get_bert_analyzer()
    
    if not analyzer._session:
        print("错误: BERT 模型未加载")
        return 1
    
    print("BERT 初始化成功\n")
    
    # 查找文件
    print("正在扫描记忆文件...")
    memory_files = find_memory_files(SCAN_DIRS)
    print(f"找到 {len(memory_files)} 个记忆文件\n")
    
    if args.limit:
        memory_files = memory_files[:args.limit]
        print(f"限制处理前 {args.limit} 个文件\n")
    
    # 处理文件
    total_stats = defaultdict(int)
    start_time = time.time()
    
    for i, file_path in enumerate(memory_files, 1):
        rel_path = file_path.relative_to(project_root)
        
        # 显示进度
        if i % 10 == 0 or i == len(memory_files):
            print(f"\n进度: {i}/{len(memory_files)}")
        
        # 处理文件
        stats = backfill_memory_file(file_path, analyzer, args.dry_run)
        
        # 累加统计
        for key, value in stats.items():
            total_stats[key] += value
        
        # 如果有更新，显示文件名
        if stats["updated"] > 0:
            print(f"\n文件: {rel_path}")
            print(f"  更新: {stats['updated']}/{stats['total']}")
    
    # 最终统计
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("回填完成!")
    print("=" * 60)
    print(f"  处理文件数: {len(memory_files)}")
    print(f"  总记录数: {total_stats['total']}")
    print(f"  更新记录数: {total_stats['updated']}")
    print(f"  跳过记录数: {total_stats['skipped']}")
    print(f"  错误数: {total_stats['errors']}")
    print(f"  耗时: {elapsed:.1f}秒")
    
    if args.dry_run:
        print("\n[DRY RUN] 以上为预览，未实际修改文件")
        print("去掉 --dry-run 参数以执行实际修改")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
