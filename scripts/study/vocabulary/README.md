# Vocabulary wordbook build pipeline

`wordbook_builder.py` 把 ECDICT 等外部词典数据构建成 App 直接消费的词书 JSON。运行时 loader 和客户端只读取生成结果，不负责重新决定释义优先级。

## 释义顺序职责

外部词典负责回答“这个词有哪些释义”，而 `vocabulary_sense_rankings.json` 负责回答“同一 POS 下哪些义项更值得普通英语学习者先学”。ECDICT 的 `bnc` / `frq` 是词头级字段，不能当成 `lemma + POS + sense` 的义项频率，因此不会被用来给同一单词的多个 sense 排序。

构建顺序如下：

1. 按 ECDICT translation 行解析 POS 和中文释义。
2. 带已知领域标签的释义进入 `extended_translations`；普通义留在 `translations` candidate。
3. 如果 `config/study/vocabulary_sense_rankings.json` 有对应词条，则只在同一 POS 家族内部，对能够明确映射到 sense 的 source 槽位进行稳定重排。
4. 未匹配、POS 缺失、alias 歧义的 source item 保持原槽位不动；ranking 不完整时不猜未知 sense 的优先级。
5. 最后应用 `config/study/vocabulary_sense_overrides.json`。manual override 始终拥有最高优先级。
6. 没有可用 ranking 时，保持原词典顺序作为 fallback。

因此 precedence 是：

```text
manual vocabulary_sense_overrides
    > learner sense ranking for explicit matches
    > existing domain split / source dictionary order fallback
```

## Ranking schema

```json
{
  "version": 1,
  "profile": "general_learner",
  "words": {
    "perspective": {
      "n": [
        {
          "sense_id": "viewpoint",
          "rank": 1,
          "tier": "core",
          "aliases_zh": ["观点", "视角", "看法", "角度"],
          "source": ["human_seed"],
          "confidence": 0.99
        }
      ]
    }
  }
}
```

`lemma + POS + sense_id` 是语义主键。`aliases_zh` 只是把当前外部词典已有中文 translation 映射到 sense；它不是全局关键词打分规则。代码只做标点/空白归一化和 exact alias token matching，不允许出现类似 `if "观点" in translation: score += ...` 的语义硬编码。

`vt` / `vi` 可以在没有更精确配置时使用通用 `v` ranking，但 noun / verb 等不同 POS 不会互相排序或污染。

## 数据维护原则

`vocabulary_sense_overrides.json` 用于少量必须人工接管的特殊词，继续作为最高权限层。`vocabulary_sense_rankings.json` 用于可扩展的义项学习优先级数据。

第一版 ranking 可以由人工种子和离线 LLM 辅助生成，但生成结果必须经过 schema 校验并提交到 repo。正常 `build_wordbooks.py`、runtime loader 和 App 不调用 LLM，也不联网。以后如果引入 corpus + WSD，应把统计结果当成 ranking evidence，而不是把 corpus count 直接等同于 learner priority。

## 离线 LLM 草案生成

`scripts/study/vocabulary/generate_sense_rankings.py` 是独立维护工具。它读取 ECDICT 已有的同 POS candidate，并要求模型只能做 grouping / ranking；模型不能新增、改写或遗漏 candidate。返回结果会再次经过代码校验：不存在的 candidate、重复 candidate、遗漏 candidate、重复 rank、非法 tier / confidence 都会直接失败。

默认输出到：

```text
output/vocabulary_sense_rankings.generated.json
```

这个文件**不会被正常 build 自动读取**。必须人工 review 后，再把需要的条目合入正式的：

```text
config/study/vocabulary_sense_rankings.json
```

示例：

```bash
set OPENAI_API_KEY=your-key
python scripts/study/vocabulary/generate_sense_rankings.py \
  --endpoint https://your-openai-compatible-endpoint/v1/chat/completions \
  --model your-model \
  --words perspective,figure,point
```

如果不传 `--words`，脚本按 ECDICT 顺序扫描同 POS 多义词；默认最多处理 100 个 candidate group。没有可靠 POS 的 translation 不会被猜测排序。

## 用户词收录

分级词书只收带考试标签（`zk/gk/cet4/cet6/ky/toefl/ielts/gre`）的 ECDICT 词条。用户手动记到 `daily/YYYY/MM/DD.txt`、`unfamiliar_word.txt` 或已进入 `vocab_progress.json` 但没有这些标签的词，由 `collect_user_words()` 作为 `extra_words` 补进 `CET-全量.json`（report 的 `extra_words` 字段会列出）。

因此收录路径有两条：

- 完整重建：`python scripts/study/vocabulary/build_wordbooks.py --write`（会自动备份到 `Words/backups/`）。
- 运行时增量：`core/tools/study/english/wordbook_sync.py`，取词发现未收录词时后台流式扫描 ECDICT 只补缺失词，不需要整体重建 77 万行词表。

## 构建

默认 ranking 文件会自动加载，也可显式指定：

```bash
python scripts/study/vocabulary/build_wordbooks.py \
  --sense-rankings config/study/vocabulary_sense_rankings.json
```

未传 `--write` 时仍只生成统计，不覆盖成品词书。

## 回归验证

```bash
python tests/scripts/study/test_vocabulary_sense_ranking.py
```

测试覆盖 `perspective`、POS 隔离、manual override precedence、领域义分流与全领域 fallback、无 ranking fallback、partial/ambiguous ranking 的保守 fallback、确定性、首批多义词 seed ranking，以及离线 LLM 不得创造/遗漏 candidate 的约束。
