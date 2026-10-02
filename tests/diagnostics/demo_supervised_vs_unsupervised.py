#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监督学习 vs 无监督聚类 对比演示

展示记忆话题分类中两种方法的实际效果差异
"""
import sys
sys.path.insert(0, ".")


演示数据 = [
    "今天在学习Python算法，感觉很难",
    "晚上和朋友吃了火锅，很开心",
    "下午开了一个项目评审会议",
    "周末准备去旅行，攻略还没做",
    "今天跑步5公里，锻炼身体",
    "读了一本人工智能相关的书",
    "老板让我明天交报告",
    "最近睡眠质量不好，总是失眠",
    "春节回家过年，买了火车票",
    "今天写了个机器学习的小项目",
    "中午点了外卖，黄焖鸡米饭",
    "参加了技术分享会，学到很多",
    "头疼了一整天，吃了布洛芬",
    "中秋节和家人一起吃月饼",
    "项目上线了，加班到凌晨",
    "周末去爬山，风景很好",
    "在看关于深度学习的论文",
    "今天面试了一个候选人",
    "感冒发烧38度，请假休息",
    "双十一买了很多东西",
]


def 演示监督学习分类():
    """监督学习：预设类别 + 关键词匹配"""
    print("=" * 60)
    print("监督学习（Supervised Learning）- 关键词分类")
    print("=" * 60)
    
    预设类别关键词 = {
        "daily": ["今天", "晚上", "中午", "周末", "回家", "吃", "外卖", "火锅", "月饼", "买东西"],
        "learning": ["学习", "算法", "读", "书", "论文", "机器学习", "深度学习", "技术分享"],
        "work": ["项目", "会议", "报告", "老板", "加班", "面试", "上线", "评审"],
        "health": ["跑步", "锻炼", "头疼", "失眠", "感冒", "发烧", "布洛芬", "身体"],
        "festival": ["春节", "中秋节", "过年", "火车票", "双十一"],
    }
    
    结果 = {}
    for 文本 in 演示数据:
        最高分 = 0
        最佳类别 = "uncategorized"
        
        for 类别, 关键词列表 in 预设类别关键词.items():
            命中数 = sum(1 for 词 in 关键词列表 if 词 in 文本)
            if 命中数 > 最高分:
                最高分 = 命中数
                最佳类别 = 类别
        
        结果[文本] = 最佳类别
        print(f"  [{最佳类别:10s}] {文本}")
    
    return 结果


def 演示无监督聚类():
    """无监督学习：不预设类别，让数据自己分组"""
    print("\n" + "=" * 60)
    print("无监督聚类（Unsupervised Clustering）- K-Means")
    print("=" * 60)
    
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
    except ImportError:
        print("  需要安装sklearn: pip install scikit-learn")
        print("  跳过演示")
        return None
    
    print("  步骤1: 文本向量化（TF-IDF）")
    向量化器 = TfidfVectorizer(
        max_features=50,
        token_pattern=r'(?u)\b\w+\b'
    )
    向量矩阵 = 向量化器.fit_transform(演示数据)
    特征名 = 向量化器.get_feature_names_out()
    print(f"  提取了 {len(特征名)} 个关键词特征")
    print(f"  特征示例: {', '.join(特征名[:10])}")
    
    print("\n  步骤2: K-Means聚类（K=4，假设分4组）")
    聚类模型 = KMeans(n_clusters=4, random_state=42, n_init=10)
    聚类标签 = 聚类模型.fit_predict(向量矩阵)
    
    print("\n  步骤3: 查看聚类结果（机器自动分组，没有类别名）")
    结果 = {}
    for 簇号 in range(4):
        print(f"\n  簇 {簇号}（共{(聚类标签==簇号).sum()}条）:")
        簇内文本 = [演示数据[i] for i in range(len(演示数据)) if 聚类标签[i] == 簇号]
        for 文本 in 簇内文本:
            结果[文本] = f"簇{簇号}"
            print(f"    [簇{簇号}] {文本}")
    
    return 结果


def 对比分析(监督结果, 无监督结果):
    """对比两种方法的效果"""
    print("\n" + "=" * 60)
    print("对比分析")
    print("=" * 60)
    
    print("\n监督学习的优势：")
    print("  ✅ 类别名有意义（daily/learning/work）")
    print("  ✅ 可解释性强（因为命中关键词）")
    print("  ✅ 稳定可控（同样的输入总是同样的输出）")
    print("  ✅ 符合业务需求（预设的业务类别）")
    
    print("\n无监督聚类的特点：")
    print("  ❓ 簇名没有意义（只是'簇0'、'簇1'）")
    print("  ❓ 分组不可控（算法决定怎么分）")
    print("  ❓ 可能不符合业务逻辑")
    print("  ✅ 可能发现人类没想到的模式")
    
    print("\n示例对比：")
    for 文本 in 演示数据[:5]:
        监督类别 = 监督结果[文本]
        聚类簇 = 无监督结果.get(文本, "未知") if 无监督结果 else "N/A"
        print(f"  文本: {文本}")
        print(f"    监督: {监督类别}  |  无监督: {聚类簇}")


def main():
    print("记忆话题分类：监督学习 vs 无监督聚类 对比演示\n")
    
    监督结果 = 演示监督学习分类()
    无监督结果 = 演示无监督聚类()
    
    if 无监督结果:
        对比分析(监督结果, 无监督结果)
    
    print("\n" + "=" * 60)
    print("结论")
    print("=" * 60)
    print("对于话题分类任务：")
    print("  → 监督学习（关键词匹配）是更合适的选择")
    print("  → 无监督聚类适合发现相似记忆，不适合预设分类")
    print("=" * 60)


if __name__ == "__main__":
    main()
