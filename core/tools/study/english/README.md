# 背单词模块（core/tools/study/english）

> 由解耦后的 VocabularyManager 组合而成，面向对外 API 提供单例门面。

## 模块结构

| 文件 | 职责 |
|------|------|
| `loader.py` | `VocabDataStore`：路径解析、词典/例句/进度懒加载与落盘、单词/例句查询、导入/切换 |
| `fsrs_scheduler.py` | FSRS(`Scheduler`/`Card`)间隔调度 + SM-2 回退 + quality→Rating 映射 + daily/unfamiliar 同步 |
| `quiz.py` | `get_daily_words`（昨天 daily 生词 + FSRS 到期词）、测验生成与判分、加学 |
| `stats.py` | 统计、错词/弱词、App 错题与 unfamiliar 计数合并、记忆曲线、`get_review_overview`、streak、手动背诵统计 |
| `daily_word_log.py` | 每日生词日志 `daily/YYYY/MM/DD.txt`（单例） |
| `unfamiliar_word_book.py` | 历史生词本文件读写 |
| `vocab_review_reminder.py` | 复习定时提醒（APScheduler，通道留接口） |
| `vocabulary_manager.py` | `VocabularyManager` Facade + `get_vocabulary_manager()` 单例，对外 API 入口 |

## 词书来源

- 词书由 `scripts/study/vocabulary/build_wordbooks.py` 基于 **ECDICT**（`external/ECDICT-master/ecdict.csv`）可复现重建，筛选 8 个考纲标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）并保留进度、daily、unfamiliar 手动补词；默认干跑，显式 `--write` 才覆盖成品并自动备份。
- `CET-全量.json`：全量释义总表约 1.5 万词，每条带 `tags` 标注所属级别；仅作复习释义兜底查询，不显示在词书选择列表。
- 分级词书（词书选择页按级别切换，背新词按当前词书取词）：
  - `CET4-顺序.json`：四级基础（zk∪gk∪cet4，默认词书）
  - `CET6-顺序.json` / `考研-顺序.json` / `托福-顺序.json` / `雅思-顺序.json` / `GRE-顺序.json`
- 释义解析保留 `vt/vi` 等真实词性；`[经][机][医][化]` 等领域义写入 `extended_translations`，不再与普通义混排。Sentence 文件只贡献例句、短语和音标，附带的 `translations` 永不进入词书释义。
- `config/study/vocabulary_sense_overrides.json` 是人工核对覆盖层；只有其中的 `primary_translations` 才带 `primary=true` 并在 App 加粗，禁止自动加粗数组第一项。原始 ECDICT 释义仍保留在折叠扩展区。
- 复习释义查询：当前词书优先，查不到回退全量总表（`loader.get_word_info`）。
- 进度文件：`output/user_data/vocab_progress.json`（FSRS 状态以 `fsrs_` 前缀存储，UTC 时间戳）。

## 复习调度要点

- `get_daily_words(limit=0)`：第一阶段取昨天 `daily/YYYY/MM/DD.txt` 生词（词书查不到也保留），
  第二阶段补 FSRS 到期且「今天未 last_review」的词（避免刚 Again 的词立刻重排）。
- 前端 Again：本轮最多重排 2 次；结算页按单词去重统计会/不会。

## AI 双来源与 App 联动

- `word_quiz` 支持 `daily` / `unfamiliar` / `both` 三种来源；未指定来源时走 `daily`，未指定 `date`/`days` 时固定读取昨天的日志。显式传 `days` 才合并最近多日。
- 工具结果始终返回 `source`；`daily` 还返回 `scope`、`dates_with_words`，`both` 将两类结果放在独立分区，避免模型把空的 daily 结果说成 unfamiliar 的旧结果。
- AI 的 unfamiliar 抽词池是长期文件与 App 历史错误次数的只读合并视图，因此旧错题也会立即参与优先抽词，无需改写原文件；App 提交 `quality<=2` 时，FSRS 进度、当天 daily 日志和长期 unfamiliar 难度计数同时更新，`quality>=3` 时 unfamiliar 计数减一（最低 0）。
- `/api/v1/vocab/mistakes` 合并进度历史错误次数与 unfamiliar 当前计数，`error_count` 取两者较大值以避免 App 同一次错误被重复相加，并保留 `progress_error_count`、`unfamiliar_count`、`sources` 供诊断。

## 外部调用

对外统一走 `get_vocabulary_manager()`；后端服务层 `core/services/study/service.py` 透传；
安卓端 `StudyVocabReviewManager` 负责复习会话。
