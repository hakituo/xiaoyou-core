# 情绪系统模块 (Emotion System)

## 概述

本模块负责 Xiaoyou 虚拟伴侣的情绪状态管理，包括情绪检测、衰减累积、持久化和硬件联动。

## 核心架构

```
├── __init__.py           # 模块导出
├── models.py             # 数据模型定义
├── constants.py          # 常量配置
├── calculator.py         # 情绪计算引擎
├── detector_v2.py        # 情绪检测器 V2（Legacy：LLM标签提取）
├── detector_smart.py     # 智能情绪检测器（默认：关键词+BERT）
├── manager.py            # 情绪管理器（Facade）
└── store.py              # 持久化存储
```

---

## 数据模型

### EmotionType
支持的情绪类型（15种）：
- `neutral` - 平静
- `happy` - 开心
- `sad` - 难过
- `angry` - 生气
- `anxious` - 焦虑
- `tired` - 疲惫
- `shy` - 害羞
- `excited` - 兴奋
- `jealous` - 吃醋
- `wronged` - 委屈
- `coquetry` - 撒娇
- `lost` - 迷茫
- `lonely` - 孤独
- `fear` - 害怕

### EmotionState
情绪状态数据类：
```python
@dataclass
class EmotionState:
    primary_emotion: EmotionType  # 主导情绪
    confidence: float              # 置信度
    sub_emotions: Dict[str, float] # 子情绪分布
    emotion_mix: Dict[str, float]  # 情绪混合
    timestamp: float               # 时间戳
    intensity: float               # 强度
    context: Optional[str]         # 上下文
    source: str                    # 来源（keyword/bert/hybrid）
```

---

## 核心组件详解

### 1. 智能情绪检测器 (EmotionDetectorSmart) ⭐ 默认

**文件**: `detector_smart.py`

**检测策略**: 双路径融合

```
输入文本 → 并行处理
├─ Fast Path（关键词）→ scores_1
└─ BERT Path（语义）→ scores_2
         ↓
      融合策略（60% + 40%）
         ↓
    多情绪分布输出
```

#### Fast Path（关键词路径）

**功能**:
- 关键词匹配（基于 `EMOTION_DEFINITIONS`）
- Emoji 情绪映射
- 否定词处理（"不开心" → neutral）
- 程度副词增强（"超级开心" → 强度 ×1.5）

**否定词列表**:
```python
{"不", "没", "别", "非", "无", "没有", "未曾", "不要", "不能", "不会", ...}
```

**程度副词映射**:
| 副词 | 倍率 |
|-----|------|
| 超级/超 | ×1.5 |
| 太/非常/特别 | ×1.4 |
| 很/好/真 | ×1.3 |
| 有点/稍微 | ×0.7~0.8 |

**示例**:
| 输入 | 分析 | 结果 |
|------|------|------|
| "好开心" | 匹配"开心" | `{happy: 1.0}` |
| "超级开心" | "超级"×1.5 | `{happy: 1.0}` (强度更高) |
| "不开心" | 否定词翻转 | `{neutral: 1.0}` |
| "好难过好委屈" | 多关键词 | `{sad: 0.5, wronged: 0.5}` |

#### BERT Path（语义路径）

**功能**:
- 使用 `bge-small-zh-v1.5` 模型
- 零样本分类（Zero-Shot）
- 理解语义相似度

**算法流程**:
```python
# 1. 文本编码
content_emb = bert._get_text_embedding(text)  # 768维向量

# 2. 归一化
content_emb = content_emb / np.linalg.norm(content_emb)

# 3. 计算与各情绪原型的相似度
for emo, proto_emb in emotion_embeddings.items():
    score = np.dot(content_emb, proto_emb)  # 余弦相似度

# 4. 归一化为概率分布
scores = {k: v / total for k, v in scores.items()}
```

**可视化示例**:
```
文本: "今天心情不太好"
    ↓ BERT 编码
向量: [0.15, -0.23, 0.41, ...] (768维)
    ↓ 计算相似度
happy原型: 0.25
sad原型:   0.72  ← 最相似
neutral:   0.31
    ↓ 归一化
结果: {sad: 0.45, neutral: 0.20, happy: 0.16}
```

#### 融合策略

```python
# 默认权重
keyword_weight = 0.6  # 关键词占 60%
bert_weight = 0.4     # BERT 占 40%

# 融合公式
final_scores[emo] = (
    fast_scores.get(emo, 0) * keyword_weight +
    bert_scores.get(emo, 0) * bert_weight
)
```

**融合示例**:
```
输入: "今天好难过啊"

Fast Path: {sad: 0.85, wronged: 0.15}
BERT Path: {sad: 0.65, lonely: 0.20, neutral: 0.15}

融合后:
sad = 0.85 × 0.6 + 0.65 × 0.4 = 0.77
wronged = 0.15 × 0.6 = 0.09
lonely = 0.20 × 0.4 = 0.08

最终: {sad: 0.77, wronged: 0.09, lonely: 0.08}
```

---

### 2. 情绪检测器 V2 (EmotionDetectorV2) - Legacy

**文件**: `detector_v2.py`

**实现**: LLM 标签提取（已弃用，保留兼容）

**检测格式**:
- `[EMO: sad]` → 置信度 0.95
- `[sad]` → 置信度 0.90

**切换方式**:
```python
# 使用 Legacy 模式
manager = EmotionManager({"detector_mode": "legacy"})
```

---

### 3. 情绪计算引擎 (EmotionCalculator)

**文件**: `calculator.py`

**功能**:
- 时间衰减：基于指数衰减模型
- 情绪累积：平滑叠加而非直接覆盖
- 子情绪管理

#### 时间衰减 (Time Decay)
```python
decay_factor = 1 - exp(-ln(2) * elapsed_seconds / half_life)
```
- 半衰期：默认 300 秒（5分钟）
- 5分钟后衰减一半，10分钟后衰减75%

#### 情绪累积 (Emotion Accumulation)
```python
increment = (1 - current_value) * new_score * accumulation_rate
new_value = min(current_value + increment, max_intensity)
```

---

### 4. 情绪管理器 (EmotionManager)

**文件**: `manager.py`

**设计模式**: Facade + Singleton + Thread-Safe

**检测模式**:
| 模式 | 说明 |
|------|------|
| `smart`（默认） | 关键词 + BERT 融合检测 |
| `legacy` | LLM 标签提取 |

**核心职责**:
1. 协调检测器、计算器、存储
2. 管理用户级和全局情绪状态
3. 注入生命系统影响
4. 生成对话情感提示词
5. 硬件联动（灯光、呼吸率）

**关键方法**:

| 方法 | 功能 |
|------|------|
| `process_text(user_id, text)` | 检测情绪并更新状态 |
| `apply_influence(user_id, weights, source)` | 应用外部情绪影响 |
| `ingest_life_stats(user_id, life_stats, intimacy)` | 生命系统联动 |
| `build_dialogue_affect_instruction(...)` | 生成情感提示词 |
| `get_hardware_payload(user_id)` | 获取硬件控制意图 |

**生命系统 → 情绪映射**:
| 生命指标 | 情绪权重 |
|---------|---------|
| 心情 ≤ 20 | `lost(0.85)`, `sad(0.55)` |
| 心情 ≥ 85 | `happy(0.65)`, `excited(0.35)` |
| 害羞 ≥ 70 | `shy(0.25~0.80)` |
| 生病/免疫 ≥ 50 | `tired(0.25~0.75)`, `anxious(0.25)` |
| 亲密度 ≥ 0.8 | `coquetry(0.45)` |

**情绪 → 硬件映射**:
| 情绪 | 颜色 | 呼吸率(ms) |
|-----|------|-----------|
| angry | #FF0000 | 1000 |
| excited | #FFA500 | 1500 |
| happy/coquetry | #FFDF00 | 3000 |
| shy | #FFC0CB | 3500 |
| neutral | #FFFFFF | 4000 |
| sad/lonely | #6495ED | 5000 |
| tired | #808080 | 6000 |

---

### 5. 持久化存储 (EmotionStore)

**文件**: `store.py`

**设计**:
- 后台线程批量写入
- JSONL 格式存储
- 内存缓存（最近100条）

**文件路径**: `data/emotions/{user_id}_history.jsonl`

---

## 完整流程

```
用户消息 → ChatAgent
    ↓
生命系统状态 → ingest_life_stats() → 影响情绪
    ↓
build_dialogue_affect_instruction() → 注入 prompt
    ↓
LLM 生成回复（不需要打标签）
    ↓
process_text(full_content) → 智能检测情绪
    ↓
get_response_strategy() → 呼吸灯控制
```

---

## 使用示例

```python
from core.emotion import get_emotion_manager

# 获取单例（默认 smart 模式）
manager = get_emotion_manager()

# 处理文本（自动检测情绪）
state = manager.process_text("user_001", "今天好难过啊 😢")
print(state.primary_emotion)  # EmotionType.SAD
print(state.intensity)        # 0.77
print(state.source)           # "hybrid" 或 "keyword" 或 "bert"

# 应用生命系统影响
manager.ingest_life_stats("user_001", {
    "mood_score": 25,
    "shyness_score": 80,
    "is_sick": False
}, intimacy_level=0.7)

# 构建情感提示词
prompt = manager.build_dialogue_affect_instruction(
    user_id="user_001",
    mood_score=25,
    intimacy_level=0.7
)
# 输出: "当前情绪难过(77%); 回复风格: 语气更温和，适度亲近"

# 获取硬件控制
hw = manager.get_hardware_payload("user_001")
# {'light': {'color': [100, 149, 237], 'mode': 'breathing', 'interval': 5000, 'brightness': 0.77}}
```

---

## 配置项

```python
{
  "detector_mode": "smart",        # 检测模式: smart/legacy
  "keyword_weight": 0.6,           # 关键词权重
  "bert_weight": 0.4,              # BERT权重
  "keyword_only": False,           # 仅关键词模式
  "decay_rate": 0.2,               # 衰减速率系数
  "accumulation_rate": 0.3,        # 累积速率系数
  "time_decay_half_life": 300.0,   # 时间衰减半衰期(秒)
  "max_recent_influences": 32,     # 最多保留影响记录数
  "data_dir": "data/emotions"      # 存储目录
}
```

---

## 情绪定义文件

**文件**: `core/services/data_ops/bert_definitions.py`

```python
EMOTION_DEFINITIONS = {
    "happy": ["开心", "高兴", "快乐", "😄", "😆", ...],
    "sad": ["难过", "伤心", "悲伤", "😢", "😭", ...],
    "angry": ["生气", "愤怒", "气死", "😠", "😡", ...],
    # ... 15种情绪
}
```

---

## 相关模块

- `core/services/data_ops/bert_analyzer.py` - BERT 分析器
- `core/services/data_ops/bert_definitions.py` - 情绪定义
- `core/agents/chat_agent_components/handler.py` - 对话处理
- `core/services/active_care/` - 主动关怀
- `core/services/life_simulation/` - 生命系统

---

## 测试

```bash
python tests/diagnostics/test_emotion_detector.py
```

---

## 研究方向（论文级）

### 已实现
- ✅ 关键词检测（否定词、程度副词）
- ✅ BERT 零样本分类
- ✅ 多情绪分布输出
- ✅ 时间衰减模型

### 待研究
1. **BERT 微调**: 使用中文情感数据集训练分类头
2. **时序建模**: 马尔可夫链 / GRU 建模情绪转移
3. **个性化**: 学习用户情绪基线
4. **反讽检测**: "你可真厉害啊" 的语义理解
5. **多模态**: 文本 + 语音 + 表情融合
