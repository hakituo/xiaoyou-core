#!/usr/bin/env python3
import math
import re
import json
import os
from collections import Counter
from typing import List, Tuple, Optional
from core.utils.logger import get_logger

logger = get_logger("ad_classifier")

AD_TRAINING_DATA = [
    ("【广告】AI培训课程限时优惠！零基础学大模型开发", True),
    ("限时优惠！Python全栈开发课程，原价9999现价3999", True),
    ("免费领取AI大模型学习资料包，名额有限先到先得", True),
    ("双11特惠！云服务器低至1折，新用户专享", True),
    ("优惠券已到账！满100减50，点击立即使用", True),
    ("秒杀活动进行中！GPU算力限时5折，抢完即止", True),
    ("报名即送面试辅导和就业推荐！名额有限", True),
    ("原价1999元，限时免费！AI绘画课程", True),
    ("红包雨来了！最高可领888元，仅限今日", True),
    ("包邮特惠！编程书籍5本套装，折扣价99元", True),
    ("首月0元体验！AI写作助手Pro会员", True),
    ("返利活动：购买算力卡返20%余额", True),
    ("打折促销！大模型API调用包年8折", True),
    ("领券立减200！深度学习训练营", True),
    ("特价！ChatGPT账号代注册，10元/个", True),
    ("限时折扣！A100 GPU租用低至2元/小时", True),
    ("免费试用30天！企业级AI对话平台", True),
    ("爆款推荐！AI课程合集，3人拼团价99", True),
    ("充值返现！充100送50，仅限本周", True),
    ("买一送一！AI编程助手年度会员", True),
    ("新课上线！原价5999，早鸟价1999", True),
    ("推广有礼！邀请好友各得50元优惠券", True),
    ("清仓特卖！AI相关书籍3折起", True),
    ("会员日！全站课程6折，叠加优惠券更低", True),
    ("限时秒杀！RTX 4090显卡直降2000", True),
    ("DeepSeek推出V3模型，在多项基准测试中超越GPT-4o", False),
    ("智谱AI发布GLM-5系列，支持原生工具调用和深度推理", False),
    ("月之暗面推出Kimi-K2，在代码生成领域表现突出", False),
    ("DeepSeek V3采用MoE架构，总参数671B，激活参数37B", False),
    ("在MMLU、HumanEval等基准上达到SOTA水平", False),
    ("训练成本仅557万美元，远低于GPT-4的1亿美元", False),
    ("该模型完全开源，支持商业使用", False),
    ("智谱AI发布GLM-5系列模型，首次在单个模型中实现推理编码和Agent能力原生融合", False),
    ("GLM-5总参数3550亿，激活参数320亿，支持128K上下文", False),
    ("在SWE-Bench、TAU-Bench等Agent评测中表现优异", False),
    ("可作为Claude Code的替代方案", False),
    ("百度文心大模型4.5 Turbo版本发布", False),
    ("阿里通义千问Qwen3系列全面开源", False),
    ("2025年，中国AI大模型领域迎来爆发式增长", False),
    ("OpenAI发布GPT-5，在推理和代码生成方面取得重大突破", False),
    ("Meta发布Llama 4，开源模型性能再创新高", False),
    ("Google DeepMind推出Gemini Ultra 2.0", False),
    ("英伟达CEO黄仁勋在CES上展示新一代AI芯片", False),
    ("中国AI调用量首次超过美国，周调用量达5.16万亿Token", False),
    ("阿里宣布未来3年投入超3800亿元用于云和AI基础设施建设", False),
    ("DeepSeek-R1成为首个具备推理能力的开源模型", False),
    ("Qwen在2025年12月单月下载量超过接下来8家之和", False),
    ("Monica发布全球首款通用AI智能体Manus", False),
    ("2025年手机选购指南：iPhone 17 Pro Max、华为Mate 70 Pro+对比评测", False),
    ("Python 3.13正式发布，性能提升显著", False),
    ("Rust语言在系统编程领域持续增长", False),
    ("GitHub Copilot新增代码审查功能", False),
    ("Docker Desktop 5.0发布，支持AI工作负载", False),
    ("Kubernetes 1.32发布，新增AI调度优化", False),
    ("TypeScript 6.0发布，类型系统全面升级", False),
    ("Linux内核6.12发布，改进AI加速器支持", False),
    ("VS Code新增AI辅助调试功能", False),
    ("Stack Overflow 2025开发者调查报告出炉", False),
]

AD_WEIGHT_FILE = os.path.join(os.path.dirname(__file__), "ad_classifier_weights.json")


class NaiveBayesAdClassifier:
    """朴素贝叶斯广告分类器

    用于过滤搜索结果中的广告和无关推广内容。
    基于词频特征，计算P(ad|text)和P(content|text)，
    选择概率更大的类别。
    """

    def __init__(self):
        self.ad_word_counts: Counter = Counter()
        self.content_word_counts: Counter = Counter()
        self.ad_total: int = 0
        self.content_total: int = 0
        self.vocab_size: int = 0
        self.ad_doc_count: int = 0
        self.content_doc_count: int = 0
        self._trained: bool = False

    def _tokenize(self, text: str) -> List[str]:
        """中文分词：基于字符n-gram + 关键词提取"""
        tokens = []

        # 1-gram（单字）
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)

        # 2-gram（双字词）
        chars = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])

        # 3-gram（三字词）
        for i in range(len(chars) - 2):
            tokens.append(chars[i] + chars[i + 1] + chars[i + 2])

        # 特殊标记：数字+单位模式（价格特征）
        price_patterns = re.findall(r'\d+[元折%]', text)
        tokens.extend([f'__PRICE_{p}' for p in price_patterns])

        # 特殊标记：广告标记
        ad_markers = re.findall(r'[【\[]广告[】\]]', text)
        if ad_markers:
            tokens.append('__AD_MARKER')

        # 特殊标记：感叹号（广告常用）
        if '！' in text or '!' in text:
            tokens.append('__EXCLAMATION')

        return tokens

    def train(self, data: List[Tuple[str, bool]]):
        """训练分类器"""
        self.ad_word_counts = Counter()
        self.content_word_counts = Counter()
        self.ad_total = 0
        self.content_total = 0
        self.ad_doc_count = 0
        self.content_doc_count = 0

        for text, is_ad in data:
            tokens = self._tokenize(text)
            if is_ad:
                self.ad_word_counts.update(tokens)
                self.ad_total += len(tokens)
                self.ad_doc_count += 1
            else:
                self.content_word_counts.update(tokens)
                self.content_total += len(tokens)
                self.content_doc_count += 1

        self.vocab_size = len(set(self.ad_word_counts.keys()) | set(self.content_word_counts.keys()))
        self._trained = True

        total_docs = self.ad_doc_count + self.content_doc_count
        logger.info(
            f"[AdClassifier] 训练完成: {total_docs}条样本, "
            f"广告{self.ad_doc_count}条/正常{self.content_doc_count}条, "
            f"词表{self.vocab_size}"
        )

    def classify(self, text: str) -> Tuple[bool, float]:
        """分类文本是否为广告

        Returns:
            (is_ad, confidence): 是否为广告，置信度
        """
        if not self._trained:
            return False, 0.0

        tokens = self._tokenize(text)
        if not tokens:
            return False, 0.5

        total_docs = self.ad_doc_count + self.content_doc_count
        log_p_ad = math.log(self.ad_doc_count / total_docs)
        log_p_content = math.log(self.content_doc_count / total_docs)

        alpha = 1.0
        for token in tokens:
            ad_count = self.ad_word_counts.get(token, 0)
            content_count = self.content_word_counts.get(token, 0)

            log_p_ad += math.log((ad_count + alpha) / (self.ad_total + alpha * self.vocab_size))
            log_p_content += math.log((content_count + alpha) / (self.content_total + alpha * self.vocab_size))

        # softmax归一化
        max_log = max(log_p_ad, log_p_content)
        p_ad = math.exp(log_p_ad - max_log)
        p_content = math.exp(log_p_content - max_log)
        total = p_ad + p_content

        prob_ad = p_ad / total
        return prob_ad > 0.5, prob_ad

    def save(self, filepath: str):
        """保存模型权重"""
        data = {
            "ad_word_counts": dict(self.ad_word_counts),
            "content_word_counts": dict(self.content_word_counts),
            "ad_total": self.ad_total,
            "content_total": self.content_total,
            "vocab_size": self.vocab_size,
            "ad_doc_count": self.ad_doc_count,
            "content_doc_count": self.content_doc_count,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath: str) -> bool:
        """加载模型权重"""
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ad_word_counts = Counter(data["ad_word_counts"])
            self.content_word_counts = Counter(data["content_word_counts"])
            self.ad_total = data["ad_total"]
            self.content_total = data["content_total"]
            self.vocab_size = data["vocab_size"]
            self.ad_doc_count = data["ad_doc_count"]
            self.content_doc_count = data["content_doc_count"]
            self._trained = True
            logger.info(f"[AdClassifier] 从文件加载模型: {filepath}")
            return True
        except Exception as e:
            logger.warning(f"[AdClassifier] 加载模型失败: {e}")
            return False


_classifier_instance: Optional[NaiveBayesAdClassifier] = None


def get_ad_classifier() -> NaiveBayesAdClassifier:
    """获取广告分类器单例（懒加载）"""
    global _classifier_instance
    if _classifier_instance is not None and _classifier_instance._trained:
        return _classifier_instance

    classifier = NaiveBayesAdClassifier()

    if classifier.load(AD_WEIGHT_FILE):
        _classifier_instance = classifier
        return classifier

    logger.info("[AdClassifier] 权重文件不存在，使用内置训练数据训练")
    classifier.train(AD_TRAINING_DATA)

    try:
        classifier.save(AD_WEIGHT_FILE)
    except Exception as e:
        logger.warning(f"[AdClassifier] 保存权重文件失败: {e}")

    _classifier_instance = classifier
    return classifier
