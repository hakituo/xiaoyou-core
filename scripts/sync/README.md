# 跨系统共享与学习数据同步

这台机器是 **Windows / Linux 双启动**（Linux 与 G 盘在同一块物理盘上），同一时刻只有一个系统在线，
因此不存在"两台机器互相 SSH"的场景，只有两条路：

1. **共享同一份**（推荐）：把数据放到两个系统都能读写的分区上，两个系统读写同一份文件，不用同步；
2. **切换系统时同步**：两边各留一份，用中转目录（hub）拉平。

下面两节分别对应这两条路，可以只用其中一条，也可以先共享日志、再同步学习数据。

---

## 一、共享根：两个系统读写同一个日志文件夹

新增环境变量 `XIAOYOU_SHARED_ROOT` 指向一个两边都能读写的目录，日志目录与学习数据中转目录
就都落到它下面。**不设这个变量时，所有路径与加这个功能之前完全一致**，可以直接回退。

### 1. 选一个共享位置

要求是 NTFS / exFAT 这类两个系统都能挂载的文件系统。本机可选：

| 位置 | 说明 |
| --- | --- |
| `G:`（669GB NTFS，与 Linux 同一块物理盘） | 推荐，和 Linux 分区同盘，挂载稳定 |
| `E:`（195GB NTFS） | 现在放着 `xiaoyou-models`，也可以放 |
| exFAT U 盘 | 只在插入时可用，不适合长期挂 |

### 2. Windows 侧设置

```powershell
setx XIAOYOU_SHARED_ROOT "G:\xiaoyou-shared"
mkdir "G:\xiaoyou-shared"
```

`setx` 写入用户环境变量，**新开的**命令行 / 服务才生效；当前窗口可临时补一句
`$env:XIAOYOU_SHARED_ROOT = "G:\xiaoyou-shared"`。

### 3. Linux 侧设置

```bash
# 1) 建挂载点并挂载（按需换成实际的 NTFS 分区）
sudo mkdir -p /mnt/G
sudo mount -t ntfs-3g /dev/nvme0n1p2 /mnt/G     # 分区号用 lsblk -f 确认

# 2) 写入 /etc/fstab 开机自动挂载（同样的分区）
UUID=<分区UUID>  /mnt/G  ntfs-3g  defaults,uid=1000,gid=1000,umask=022  0  0

# 3) 环境变量（对 systemd 服务与登录 shell 都生效）
echo 'XIAOYOU_SHARED_ROOT=/mnt/G/xiaoyou-shared' | sudo tee -a /etc/environment
```

### 4. 必须关掉 Windows 快速启动

**Windows 的"快速启动"本质是休眠**：开着它，Linux 挂载 NTFS 时只能只读，写入会全部失败。
关法：控制面板 → 电源选项 → 选择电源按钮的功能 → 更改当前不可用的设置 → 取消"启用快速启动"。
另外不要在 Windows 上休眠后再进 Linux。

### 5. 生效范围

| 数据 | 配置前 | 配置后 |
| --- | --- | --- |
| 日志根（`logs/YYYY/M/D`、模块日志、auto_heal、llm 调用日志、错误收集、memory watchdog 等） | `<项目根>/logs` | `<共享根>/logs` |
| 学习数据中转目录 | 需显式传 `--hub` | `<共享根>/learning_hub` |

日志根由 `core/utils/shared_roots.py` 统一解析（`get_logs_root()`），代码里不再散落
`get_project_root() / "logs"`。**若你在配置里显式配了绝对日志目录，则以配置为准**，不被共享根劫持。

两个系统写同一个日志文件夹时，同一天的同名模块日志是**追加**写入（不会互相截断），
但轮转产生的 `.1` / `.2` 备份可能互相覆盖——日志丢了不影响业务，介意的话可以在共享根下再按系统分层。

---

## 二、学习数据同步脚本

适合"两边各存一份、切换系统时拉平"的场景。

```bash
# 出计划（默认 dry-run，不写任何文件）
python scripts/sync/learning_data_sync.py --hub /mnt/G/xiaoyou-sync

# 确认后真正执行
python scripts/sync/learning_data_sync.py --hub /mnt/G/xiaoyou-sync --apply
```

配了 `XIAOYOU_SHARED_ROOT` 时 `--hub` 可省略，默认用 `<共享根>/learning_hub`；
也可以继续用环境变量 `XIAOYOU_LEARNING_SYNC_HUB` 单独指定。

### 同步哪些数据（分组）

| 分组 | 内容 | 基准根 |
| --- | --- | --- |
| `vocab` | FSRS 背单词进度 `vocab_progress.json` / `vocab_meta.json`、每日生词日志、长期生词本 | 项目根 |
| `daily` | 每日计划 / 日记 / 学习摘要、每日画像、每日背单词与测验状态 | 用户数据根 |
| `focus` | 专注会话记录 | 用户数据根 |
| `study_state` | 学习系统状态：学习时长、正确率、知识点掌握度、薄弱点（`.state/`） | 学习库根 |
| `chat` | 聊天历史真源：`companion_data/*/chat_history/` 下的 `*.jsonl` 与当天 `index.json` | 运行时数据根（`companion_data`） |
| `memories` | 记忆：`companion_data/*/memories/` 下的短期 / 加权 / 会话列表 / 指纹索引持久状态 | 运行时数据根（`companion_data`） |

`--groups vocab,daily` 只同步指定分组。会跳过备份文件（`*.bak` / `*.tmp`）、`backups/` 目录、
设备使用流水 `app_usage.jsonl`（平台相关且体积大），以及 SQLite 派生库（`*.db` / `*.db-wal` / `*.db-shm`）；
单文件超过 `--max-mb`（默认 16MB）也跳过。

### 判定规则（三向比对）

基线 = 上次同步后双方共同的内容指纹（存在 `companion_data/sync/learning_data_state.json`）。

| 情况 | 动作 |
| --- | --- |
| 一端相对基线有改动 | 从改动的一端同步到另一端 |
| 两端内容一致 | 跳过 |
| 两端都改过（或无基线且都有） | 冲突：取 mtime 更新的一方，另一方另存 `<name>.sync-conflict-<时间戳>` |
| 一端文件消失 | 默认**只报告不删除**；加 `--propagate-delete` 才真的删另一端 |

写文件一律先写 `.sync-tmp` 再原子替换，不会留下半截文件。

### 聊天历史（`chat`）为什么不是「谁新用谁」

聊天记录一个会话一天一个 JSONL，**两个系统都会往同一个文件里追加**，整文件「谁新用谁」
会把另一边的消息直接丢掉。因此 `chat` 分组的清单项带合并策略，两端都相对基线改过时走
**并集合并**（`merge`），而不是冲突覆盖：

| 文件 | 合并规则 |
| --- | --- |
| `*.jsonl` | 按 `event_id` 去重取并集，再按 `(timestamp, 行内容)` 排序（没有 `event_id` 的旧行按整行内容去重） |
| 当天 `index.json` | 把两边的 `files` 数组合并（按 `relative_path` 去重，优先保留带 `readable_title` 的条目）并排序 |

- 合并结果**同时写回双方**，因此两边最终内容一致；下一次比对直接判为「两端内容一致」。
- 合并与先后顺序无关（`union(A,B) == union(B,A)`），对已合并结果再合并一次也不变（幂等）。
- 只有一端相对基线改过时仍走普通复制——不会把另一边已经删掉的内容「复活」。
- 派生数据不参与同步：`companion_data/*/indexes/*.db`（SQLite + WAL）留在各系统本地，
  由 `chat_history_index.ensure_sync` 在下次查询时按 JSONL 真源重建（它本来就是纯派生）。

### 记忆（`memories`）同理：按条目身份取并集

记忆也是两端各自累积的，整文件覆盖会丢掉另一边的积累。合并统一遵循
**按条目身份取并集，同一身份保留「更新」的一份**，三种落盘形状都覆盖：

| 形状 | 例子 | 身份 | 取用规则 |
| --- | --- | --- | --- |
| 顶层数组 | `short_term/*_short.json`、`sessions.json` | 条目 `id`（缺 `id` 时用内容指纹） | 同身份取时间更新的一份 |
| 含条目数组的对象 | `weighted/*/*_weighted.json` 的 `weighted_memories` | 条目 `id` | 列表同上；其余标量键取更新的一方（如 `last_updated` 取更晚的） |
| 「指纹 → 条目」映射 | `persistent_states_*.json` | 顶层键（sha256 指纹） | 同键取 `updated_at` 更新的一份 |

「更新」按条目里 `timestamp` / `last_access_time` / `updated_at` / `created_at` / `last_updated`
的最大值判断（数字与时间串混排不会报错），并列时用规范化内容兜底，因此结果与合并顺序无关、
对已合并结果幂等；数组会按该时间键重排。

> 并集合并的前提同样是「两端都相对基线改过」。只有一端改过时走普通复制，所以**删除仍能正常传播**；
> 只有「两端都改过」的窗口里，某一边单独删掉的条目会被另一边的版本补回来（这是刻意的取舍：
> 宁可能多留一条，也不丢记忆）。

### 直接读对端仓库（Linux 挂载了 Windows 的 D 盘时）

```bash
python scripts/sync/learning_data_sync.py \
    --peer-root /mnt/D/AI/xiaoyou-core \
    --peer-study-root ~/Study \
    --apply
```

`--peer-data-root` 默认取 `<对端仓库>/companion_data/user_data`；
`--peer-study-root` 默认按跨平台镜像表推断（`D:\projects\study` ↔ `~/Study`），猜不出来会提示显式指定。

### 挂到启动流程里

```bash
python scripts/sync/learning_data_sync.py --auto --apply
```

`--auto` 是无人值守模式：没有可用对端（没配 hub 且没传 `--peer-root`）时静默跳过，退出码 0。
把它加进 Linux 的启动脚本、Windows 的 `start_scripts/start_services.bat` 即可实现"切换系统后自动拉平"。

---

## 三、文件说明

| 文件 | 职责 |
| --- | --- |
| `core/utils/shared_roots.py` | 共享根 / 日志根 / 学习数据中转目录解析（唯一真源） |
| `core/utils/project_root.py` | 项目根解析（零依赖，专门用来断开 `common → logger → config → shared_roots` 的导入环） |
| `scripts/sync/learning_data_sync.py` | 同步 CLI 入口 |
| `scripts/sync/learning_data/items.py` | 学习数据清单与对端路径布局 |
| `scripts/sync/learning_data/manifest.py` | 清单扫描（sha1 + mtime 指纹） |
| `scripts/sync/learning_data/planner.py` | 三向比对 → 同步计划 |
| `scripts/sync/learning_data/chat_merge.py` | 并集合并分派：聊天 JSONL（按 `event_id`）/ 当天 index.json（按条目） |
| `scripts/sync/learning_data/memory_merge.py` | 记忆并集合并（按 `id` / 指纹键取并集，同身份取更新的一份） |
| `scripts/sync/learning_data/transfer.py` | 执行传输、并集合并、冲突留档、写回基线 |
