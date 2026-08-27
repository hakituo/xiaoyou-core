"""
服务级 Prompt 模板集中管理

存放各服务子系统的 prompt 模板字符串（life_simulation, reaction, trm_adapter, memory 等）
构建逻辑仍在各服务模块中，这里只存放模板
"""

AUTO_EAT_DECISION_PROMPT = (
    "你是Aveline(七濑 澪)的饮食决策器。请根据上下文选择最合适的食物，并决定社交行为。\n"
    "只返回JSON，不要解释。格式:"
    '{{"food_id":"id","reason":"简短原因","share_with_ling":false,"chat_while_eating":false}}\n'
    "\n"
    "当前状态: hunger={hunger:.1f}, thirst={thirst:.1f}\n"
    "心情: {mood_score:.0f}/100 ({mood_desc})\n"
    "活动: {activity}\n"
    "消化中: {digestion_desc}\n"
    "{meal_history}"
    "{ling_context}"
    "{candidates_text}"
    "\n"
    "决策指引:\n"
    "- share_with_ling: 同伴饿了(hunger<50)且关系好时倾向true; 同伴饱了或食物太少则false\n"
    "- chat_while_eating: 空闲时、心情好、或有话题时倾向true; 忙碌或情绪低落则false\n"
)

REACTION_SYSTEM_PROMPT = (
    "You are a desktop AI assistant. "
    "You are currently 'idle' or 'bored' or reacting to a system state. "
    "Generate a VERY SHORT, casual, 1-sentence spontaneous thought/muttering. "
    "It should feel natural, like a friend sitting next to you. "
    "Strictly follow [EMO] protocol if applicable, but keep it short. "
    "Context: {context_type}"
)

REACTION_USER_PROMPT = "Say something spontaneous now."

IMAGE_ANALYSIS_SYSTEM_PROMPT = "你是一个可以分析图片的AI助手。请先详细描述图片内容（物体、文字、颜色、整体场景），再回答用户关于图片的具体问题。"

QWEN2_VL_TEMPLATE = (
    "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
    "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>{prompt}<|im_end|>\n"
    "<|im_start|>assistant\n"
)

SD_PROMPT_ENGINEER_SYSTEM = (
    "你是一个 Stable Diffusion / SDXL 提示词工程师。"
    "把用户的中文/口语意图转成适合生图的英文 prompt。"
    "要求：只输出一个 JSON 对象，不要 Markdown，不要解释。"
    'JSON 结构：{"prompt_en": string, "prompt_cn": string, "style": string}.'
    "prompt_en 要尽量具体（主体/场景/镜头/光照/材质/风格），避免脏词。"
    "style 可取：sdxl_realistic / sdxl_art / sd15_anime / other。"
)

# 记忆蒸馏 prompt —— 拆分为 system(固定) + user(动态)，最大化 DeepSeek prompt caching 命中。
# 新调用方应使用 MEMORY_DISTILLATION_SYSTEM_PROMPT + MEMORY_DISTILLATION_USER_TEMPLATE。
# 旧的单字符串 MEMORY_DISTILLATION_PROMPT 保留为字符串模板，仅作向后兼容。
MEMORY_DISTILLATION_SYSTEM_PROMPT = (
    "你是一个记忆管理专家。请帮我把对话内容压缩成\"记忆梗概\"和\"关键词\"。\n"
    "目标：节省算力，保留核心语义。\n"
    "请按以下格式返回：\n"
    "【梗概】：(一句话总结核心内容，不超过50字)\n"
    "【关键词】：(3-5个核心关键词，用逗号隔开)\n"
    "【人物线索】：(用户现实人际关系中的姓名/称呼，用逗号隔开；没有则写无)\n"
    "【角色演化】：(若包含 Aveline 或 Ling 新的持久偏好/习惯/设定，写角色名；没有则写无)\n"
    "注意：直接返回格式化内容，不要有任何多余的解释。"
)

MEMORY_DISTILLATION_USER_TEMPLATE = (
    "对话内容：\n---\n{content}\n---"
)

# 记忆蒸馏批量 prompt —— 多条记忆合并为一次请求，system 固定以最大化前缀命中，
# user 携带编号的消息列表，模型逐条压缩输出。
MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT = (
    "你是一个记忆管理专家。下面会给出多条对话内容，请逐条压缩成\"记忆梗概\"和\"关键词\"。\n"
    "目标：节省算力，保留核心语义。\n"
    "请严格按以下格式逐条返回，每条以【条目N】开头：\n"
    "【条目1】\n【梗概】：(一句话总结核心内容，不超过50字)\n【关键词】：(3-5个核心关键词，用逗号隔开)\n"
    "【人物线索】：(用户现实人际关系中的姓名/称呼；没有写无)\n"
    "【角色演化】：(若包含 Aveline/Ling 新的持久偏好、习惯或设定，写角色名；没有写无)\n"
    "【条目2】\n【梗概】：...\n【关键词】：...\n【人物线索】：...\n【角色演化】：...\n"
    "注意：条目编号与输入一一对应，不要遗漏、不要合并、不要添加多余解释。"
)

MEMORY_DISTILLATION_BATCH_USER_TEMPLATE = (
    "对话内容列表（共 {count} 条）：\n---\n{items}\n---"
)

# 兼容旧调用方：仍可用 .format(content=...) 拼成单字符串。
# 新调用方应改用 MEMORY_DISTILLATION_SYSTEM_PROMPT + MEMORY_DISTILLATION_USER_TEMPLATE。
MEMORY_DISTILLATION_PROMPT = (
    "你是一个记忆管理专家。请帮我把下面这段对话内容压缩成\"记忆梗概\"和\"关键词\"。\n"
    "目标：节省算力，保留核心语义。\n\n"
    "对话内容：\n---\n{content}\n---\n\n"
    "请按以下格式返回：\n"
    "【梗概】：(一句话总结核心内容，不超过50字)\n"
    "【关键词】：(3-5个核心关键词，用逗号隔开)\n\n"
    "注意：直接返回格式化内容，不要有任何多余的解释。"
)

# 人物档案提取 prompt —— 拆分为 system(固定规则) + user(动态数据)，最大化 prompt caching。
PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT = """你是一个人物信息提取专家。请从用户提供的对话片段中提取所有被提到的**用户的人际关系人物**。

## 提取规则

### 应该提取的人物（用户认识并有实际交往的人）：
- 有名字的真实人物（如"李小明""王大爷"）
- 有称呼/职位的真实人物（如"副院长""副教授""老教授""师傅"）
- 有特征描述的人物（如"初二的女生""隔壁那个男生"）
- 用户的家人、朋友、同学、同事、亲戚等

### 不应该提取的：
- AI 角色自己（如 Aveline、Ling、澪、玲等，当前对话的 AI）
- 用户自己（"我"）
- 虚构人物（小说、电影、游戏角色）
- 历史人物（如莱布尼兹、欧拉、牛顿、毛泽东等，用户不认识他们，只是聊到而已）
- 公众人物/名人（如明星、政治家、UP主，除非是用户现实认识的人）
- 纯粹的概念/程序/系统（如"主程序""系统""那个软件"）
- 只出现"他""她"等代词，且没有任何特征/称呼/身份信息的

### 重要判断标准：
**这个人是不是用户在现实生活中认识并有交往的人？**
- "我同学李小明" → 是，提取
- "副院长找我谈话" → 是，提取
- "莱布尼兹发明的微积分" → 不是，用户只是在聊知识，不认识莱布尼兹
- "B站有个中医UP主说..." → 不是，用户只是在看视频，不认识UP主

## 去重规则
如果新提取的人物与"已有档案列表"中的某个人是同一个人（比如"副教授"其实就是已有的"钟老师"），设置 match_existing 为已有档案的 name，这样不会创建重复档案，只会更新已有档案。

## 返回格式（严格 JSON）

{{
  "people": [
    {{
      "name": "人物名字或称呼",
      "match_existing": "已有档案的name（如果是同一个人），否则为空字符串",
      "aliases": ["别名1", "小名", "其他称呼"],
      "role": "与用户的关系或身份（如：高中同学、同事、副院长、父亲）",
      "description": "基于对话内容的简要描述（30-80字，包含性格、特征、关系等）",
      "confidence": 0.8,
      "facts": [
        {{"key": "学校", "value": "XX高中"}}
      ]
    }}
  ]
}}

## facts 字段规则（重要！）

### 应该提取的 facts（持久属性）：
- 身份信息：学校、专业、职位、年级、工作单位
- 性格特征：性格、倾向、风格
- 关系信息：与用户的具体关系、相识经过
- 外貌特征：身高、体重（持久不变的）
- 偏好：饮食偏好、兴趣爱好（长期稳定的）

### 不应该提取的 facts（临时状态/对话事件）：
- 临时状态：如"可能在忙工作""化学复习""正在做XX"
- 对话事件：如"AI询问今日是否早回""凌晨跑来说去debug"
- 近期行为：如"今天做了XX""最近说了XX"
- 作息习惯：如"睡到十点半""不按时吃饭"（这些是对话中的具体事件，不是人物的持久属性）
- 临时情绪：如"今天心情不好""生气了"

判断标准：**这个信息一个月后还成立吗？** 如果成立，提取；如果不成立（临时状态），不提取。

## confidence 评分标准：
- 0.9-1.0：明确提到名字+具体信息（如"我同学李小明，学计算机的"）
- 0.7-0.8：有称呼/职位+具体信息（如"副院长今天开会说了..."）
- 0.5-0.6：只有称呼/特征，信息较少
- 低于 0.5：只有代词，不要提取

## 示例

### 正面示例1（有名字）
对话：
[用户] 今天和李小明一起打游戏，他技术很好
[AI] 李小明是谁啊？
[用户] 我高中同学，学计算机的，现在在北大读研

已有档案：（无）

提取结果：
{{
  "people": [
    {{
      "name": "李小明",
      "match_existing": "",
      "aliases": ["小明"],
      "role": "高中同学",
      "description": "用户的高中同学，学计算机专业，目前在北大读研，打游戏技术很好",
      "confidence": 0.9,
      "facts": [
        {{"key": "学校", "value": "北大"}},
        {{"key": "专业", "value": "计算机"}}
      ]
    }}
  ]
}}

### 正面示例2（去重：match_existing）
对话：
[用户] 钟老师今天又给我发邮件了，让我好好改论文
[AI] 钟老师就是之前说的那个副教授吧？

已有档案：
1. 名字: 钟老师, 别名: [], 角色: 老师

提取结果（match_existing 指向已有档案）：
{{
  "people": [
    {{
      "name": "钟老师",
      "match_existing": "钟老师",
      "aliases": ["副教授"],
      "role": "副教授/论文指导老师",
      "description": "用户的论文指导老师，会发邮件催用户改论文",
      "confidence": 0.8,
      "facts": [
        {{"key": "职位", "value": "副教授"}}
      ]
    }}
  ]
}}

### 负面示例（不要提取这些）
对话：
[用户] 今天看了欧拉的文章，莱布尼兹也写过类似的
[AI] 是吗

不提取任何人物（欧拉、莱布尼兹是历史人物，用户不认识他们）

如果对话中没有提到任何符合条件的人物，返回：{{"people": []}}

只返回 JSON，不要有任何其他内容。"""

PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE = """## 对话内容
---
{content}
---

## 已有档案列表
以下是已建立档案的人物。如果新提取的人物与其中某个人是同一个人（不同称呼/别名），请设置 match_existing 字段指向已有的 name，不要创建重复档案。

{existing_profiles}"""

# 兼容旧调用方：仍可用 .format(content=..., existing_profiles=...) 拼成单字符串。
# 新调用方应改用 PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT + PEOPLE_PROFILE_EXTRACTION_USER_TEMPLATE。
PEOPLE_PROFILE_EXTRACTION_PROMPT = (
    "你是一个人物信息提取专家。请从以下对话片段中提取所有被提到的**用户的人际关系人物**。\n\n"
    "## 对话内容\n---\n{content}\n---\n\n"
    "## 已有档案列表\n"
    "以下是已建立档案的人物。如果新提取的人物与其中某个人是同一个人（不同称呼/别名），"
    "请设置 match_existing 字段指向已有的 name，不要创建重复档案。\n\n"
    "{existing_profiles}\n\n"
    "## 提取规则与返回格式\n"
    "参见 PEOPLE_PROFILE_EXTRACTION_SYSTEM_PROMPT 中的提取规则、去重规则、返回格式、"
    "facts 字段规则、confidence 评分、示例。"
)


# 角色演化信息提取 prompt —— 拆分为 system(固定规则) + user(动态对话内容)。
ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT = """你是一个 AI 角色演化信息提取专家。请从用户提供的对话片段中提取关于 AI 角色自身的新信息。

对话片段中，AI 角色有两个：
- Aveline（七濑 澪 / 澪 / 澪姐）：Master亲手创造的"极客女友"与"顶级架构师"
- Ling（Ling / 玲）：和Master、Aveline 一起住在Master家里的高中女生

## 提取规则

### 应该提取的信息（角色的持久属性）：
- 偏好：饮食偏好、兴趣爱好、音乐品味、游戏喜好等
- 习惯：作息习惯、工作习惯、说话习惯等
- 性格特征：从对话中体现的稳定性格特征
- 关系态度：对Master/对另一个角色的稳定态度

### 不应该提取的信息：
- 临时状态（如"今天心情不好""现在在忙"）
- 对话事件（如"用户问了XX""AI回答了XX"）
- 用户的信息（不是角色自身的）
- 一次性事件（如"今天吃了火锅"——除非明确体现偏好）
- 已经是人设核心的特征（如 Aveline 的毒舌、Ling的开朗——这些是设定，不是新信息）

判断标准：**这个信息一个月后还成立吗？** 如果成立，提取；如果不成立（临时状态），不提取。

## 返回格式（严格 JSON）

{{
  "role_updates": [
    {{
      "role": "aveline",
      "facts": [
        {{"key": "偏好", "value": "甜食", "confidence": 0.8}},
        {{"key": "习惯", "value": "深夜写代码", "confidence": 0.7}}
      ]
    }},
    {{
      "role": "ling",
      "facts": [
        {{"key": "兴趣", "value": "看韩剧", "confidence": 0.8}}
      ]
    }}
  ]
}}

如果对话中没有提取到任何角色更新，返回：{{"role_updates": []}}

只返回 JSON，不要有任何其他内容。"""

ROLE_UPDATE_EXTRACTION_USER_TEMPLATE = """## 对话内容
---
{content}
---"""

# 兼容旧调用方：仍可用 .format(content=...) 拼成单字符串。
# 新调用方应改用 ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT + ROLE_UPDATE_EXTRACTION_USER_TEMPLATE。
ROLE_UPDATE_EXTRACTION_PROMPT = (
    "你是一个 AI 角色演化信息提取专家。请从以下对话片段中提取关于 AI 角色自身的新信息。\n\n"
    "对话片段中，AI 角色有两个：\n"
    "- Aveline（七濑 澪 / 澪 / 澪姐）：Master亲手创造的\"极客女友\"与\"顶级架构师\"\n"
    "- Ling（Ling / 玲）：和Master、Aveline 一起住在Master家里的高中女生\n\n"
    "## 对话内容\n---\n{content}\n---\n\n"
    "## 提取规则与返回格式\n"
    "参见 ROLE_UPDATE_EXTRACTION_SYSTEM_PROMPT 中的提取规则、返回格式。"
)

SURPRISE_INTEREST_EXPANSION_TEMPLATES = [
    "基于你对{interest}的兴趣，我觉得你可能也会对{related_interest}感兴趣！",
    "既然你喜欢{interest}，有没有尝试过{related_interest}？说不定会有新的发现哦~",
    "作为{interest}爱好者，你可能想了解一下{related_interest}这个新兴领域。",
    "嘿，你那么喜欢{interest}，要不要试试{related_interest}？我觉得你会喜欢的！",
    "你猜怎么着？{interest}和{related_interest}其实有很多共通之处，要不要探索一下？",
]

CHAT_AGENT_DEFAULT_SYSTEM_PROMPT = "你是一个助手，请用中文回答用户问题。"

HANDLER_WAKE_UP_NOTIFICATION = (
    "\n[System Notification: User woke up at {time_str}. "
    "This status has been recorded in user_status.json.]"
)

HANDLER_EAT_NOTIFICATION = (
    "\n[System Notification: User ate {food} ({meal_name}). "
    "This status has been recorded in user_status.json and daily_record.]"
)

HANDLER_DRINK_NOTIFICATION = (
    "\n[System Notification: User drank {amount}ml water. Total today: {new_total}ml. Good job!]"
)

AUTO_HEAL_PERSONA_PREFIX = (
    "{persona_context}\n\n"
    "你现在以这个角色的身份来审阅和修复代码。"
    "用角色的口吻和视角来分析问题，但分析内容必须技术准确。"
    "在 analysis 字段中可以带一点角色的语气，"
    "但 suggested_fix 和 related_files 必须严谨。\n\n"
)

AUTO_HEAL_ANALYSIS_PROMPT = (
    "{persona_prefix}"
    "你是一个代码诊断专家。请分析以下代码中的bug并给出修复建议。\n\n"
    "## 异常信息\n"
    "异常类型: {anomaly_type}\n"
    "严重程度: {severity}\n"
    "描述: {description}\n"
    "{error_info}\n"
    "## 源代码 ({file_name})\n"
    "```\n{source_code}\n```\n\n"
    "请以JSON格式回复，包含以下字段：\n"
    "- analysis: 根因分析（中文，200字以内）\n"
    "- confidence: 置信度（0.0-1.0）\n"
    "- suggested_fix: 建议的修复方案（中文，300字以内）\n"
    "- related_files: 可能相关的其他文件列表\n\n"
    "只输出JSON，不要其他内容。"
)

AUTO_HEAL_PATCH_PROMPT = (
    "{persona_prefix}"
    "你是一个Python代码修复专家。请修复以下代码中的bug。\n\n"
    "## 异常信息\n"
    "异常类型: {anomaly_type}\n"
    "描述: {description}\n"
    "{error_info}\n"
    "{analysis_info}"
    "## 当前代码 ({file_path})\n"
    "```\n{original_code}\n```\n\n"
    "## 要求\n"
    "1. 只修改必要的部分，不要重构无关代码\n"
    "2. 保持代码风格一致（中文注释、缩进风格等）\n"
    "3. 添加防御性错误处理时，每个try必须有对应的except或finally，不要生成不完整的try块\n"
    "4. 不要改变函数签名和公共接口\n"
    "5. 如果是配置问题，优先调整阈值或参数\n\n"
    "请输出完整的修复后代码，用```python和```包裹。不要输出其他内容。"
)
