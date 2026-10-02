# 背单词模块（core/tools/study/english）

> 由解耦后的 VocabularyManager 组合而成，面向对外 API 提供单例门面。

## 模块结构

| 文件 | 职责 |
|------|------|
| `loader.py` | `VocabDataStore`：路径解析、词典/例句/进度懒加载与落盘、单词/例句查询、导入/切换 |
| `fsrs_scheduler.py` | FSRS(`Scheduler`/`Card`)间隔调度 + SM-2 回退 + quality→Rating 映射 + daily/unfamiliar 同步 |
| `quiz.py` | `get_daily_words`（当日固定历史补漏批次 + FSRS 到期词）、测验生成与判分、加学 |
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

- `get_daily_words(limit=0)` 不做人为数量截断，返回当天首次生成的全部待复习词。历史候选写入 `_review_batch_state.json`，与 FSRS 合并后的最终全集再写入 `_review_queue_state.json`；同日重复读取或进程重启都只从这份快照中扣除完成项，不会动态补入新候选。
- 唯一例外是**用户手动编辑历史 daily 文件**：批次状态会记录各历史文件的内容签名（`source_signatures`）与本管理器自身写入的签名（`_record_self_write` / `self_written_signatures`），检测到外部编辑时只把新出现的待复习词补进当天队列（recent_retry 插在同段末尾、历史补漏追加队尾），已完成项与既有顺序不受影响；系统自身的 `mark_unknown/mark_known/remove` 写入不算外部编辑，仍不触发补位。
- 补漏扫描覆盖今天之前的全部 daily 文件并按日期从旧到新推进。某条记录从未进入进度库，或记录日期晚于最后一次复习日期时才算待处理；已有进度不会被重置。同词的 FSRS 到期项合并去重。
- 排序优先级为：最近一次仍不会的 daily 词 → FSRS 普通到期词 → 历史漏推词。`count>0` 只裁剪本次响应，不改变当天已经锁定的完整队列。
- 手动记录到 daily/生词本但分级词书没有收录的词：取词时会由 `wordbook_sync.py` 后台按 ECDICT 增量补进 `CET-全量.json`（流式扫描、只写缺失词、原子落盘、最短间隔 5 分钟），并同步刷新内存兜底词表；ECDICT 也没有的词保持「词库未收录」提示。
- daily 文本中的 `#` 标题/注释不会被解析成单词。返回项带 `review_source=daily_backlog|fsrs`，便于诊断实际来源。
- 前端 Again：本轮最多重排 2 次；结算页按单词去重统计会/不会。
- App 评分契约为 `1=Again, 2=Hard, 3=Good, 4=Easy`。调度器关闭分钟级 learning/relearning steps：Again/Hard 由 daily 日志保证第二天优先，Good/Easy 直接进入天级 FSRS，避免当天不重新拉取的分钟卡在第二天集中爆发；同时关闭 interval fuzzing，保证「从 history 重建」可重复、可验证。
- **历史评分有两套语义**（见 `LEGACY_RATING_CUTOFF`，定义在 `fsrs_scheduler.py`）：`cutoff` 之前后端按旧 0-5 量表解释（1/2→Again、3→Hard、4→Good、5→Easy），之后才是现行 1/2/3/4。`rebuild_fsrs_card_from_history` 按**事件发生时间**选择 schema，`quality_to_rating()` 只描述当前 App API，不掺历史兼容。
- 用 `scripts/maintenance/migrate_vocab_fsrs_history.py` 重算 FSRS 状态：默认 dry-run，`--apply` 自动备份到 `vocab_progress.pre_rating_migration_*.bak.json` 并写 `rating_migration_version`（幂等），`--rollback` 回滚。迁移只重算状态，不改写任何 history 的 `timestamp`/`quality`。
- quiz 自动判分只记 Good(3)/Again(1)：自动答对仅证明成功回忆，Easy 保留给用户明确表示毫不费力。
- daily 重试不再用 `quality<=2` 判断「不会」：Again 一定重试；Hard 属于成功回忆，默认交给 FSRS，只有 stability 低于 `HARD_DAILY_RETRY_STABILITY_DAYS`（新词/低稳定度）时才重看。unfamiliar 计数同口径。
- history 新增可选 `source`（`manual_review`/`quiz`/`daily_retry`/`same_session_retry`/`ai_unfamiliar_check`）；旧记录没有 source 时继续按 `manual_review` 兼容。
- Android `VocabSessionSnapshot` 升级为 v4：快照带业务日期（`date`），跨天不再恢复，避免昨天没背完的队列被当成今天的断点；旧版快照一律丢弃。本地还有未走完的队列时 `StudyVocabReviewManager.loadLearnWords` 不覆盖 `learnWords`（切 Tab 刷新不再冲掉 Again 重排到队尾的错词），会话收尾时清空会话日期让远端刷新正常接管。已提交评分仍保留在后端 FSRS。

## AI 双来源与 App 联动

- `word_quiz` 支持 `daily` / `unfamiliar` / `both` 三种来源；未指定来源时走 `daily`，未指定 `date`/`days` 时读取今天前最近的非空日志。显式传 `days` 才合并最近多日。
- 工具结果始终返回 `source`；`daily` 还返回 `scope`、`dates_with_words`，`both` 将两类结果放在独立分区，避免模型把空的 daily 结果说成 unfamiliar 的旧结果。
- AI 的 unfamiliar 抽词池是长期文件与 App 历史错误次数的只读合并视图，因此旧错题也会立即参与优先抽词，无需改写原文件；App 提交 Again（以及仍很脆弱的新词判 Hard）时，FSRS 进度、当天 daily 日志和长期 unfamiliar 难度计数同时更新，其余情况 unfamiliar 计数减一（最低 0）。
- `/api/v1/vocab/mistakes` 合并进度历史错误次数与 unfamiliar 当前计数，`error_count` 取两者较大值以避免 App 同一次错误被重复相加，并保留 `progress_error_count`、`unfamiliar_count`、`sources` 供诊断。

## 外部调用

对外统一走 `get_vocabulary_manager()`；后端服务层 `core/services/study/service.py` 透传；
安卓端 `StudyVocabReviewManager` 负责复习会话。
