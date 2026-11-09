---
name: codex-local-backup
description: 备份本机 Codex 会话、普通和压缩 session 日志及关联成果，导出可读聊天、增量历史与校验报告；用于手动备份、定期备份、检查遗漏和迁移前恢复验证。不处理云端聊天、账号解封或浏览器登录态。
metadata:
  version: "1.0.0"
---

# Codex 本地备份

这是可分发的通用 skill，不包含预设用户名、个人数据或固定备份盘。默认来源为 CODEX_HOME，未设置时为 ~/.codex；默认目标 ~/CodexBackups，可用 --source、--root 覆盖。Python 3.10+；压缩日志文本回退需要 Python 3.14+ 的 compression.zstd 或本机 zstd 命令。先确定当前 skill 的实际目录，后续脚本用绝对路径调用。

## 备份与校验

```sh
python3 <skill-dir>/scripts/backup.py backup
python3 <skill-dir>/scripts/backup.py verify --full
python3 <skill-dir>/scripts/backup.py status
```

可附加 --root <目标目录>、--source <Codex数据目录>、--include <允许收集引用文件的目录>，后者可重复。Windows 可用 py -3 替代 python3。目标必须在来源之外。

必须保存普通 .jsonl **和压缩 .jsonl.zst**，包括 sessions、archived_sessions。存在会话数据库时用 SQLite backup API 保存最高数字版本的 state_N.sqlite 和 thread_history_N.sqlite；遇到不支持的结构报告 partial，不假定所有版本兼容。只有日志的旧环境走原始日志解析。原始记录完整留存，可读文本只提取用户和助手消息，工具与其他上下文保留在原始记录中。

关联文件为尽力识别：默认从当前用户 Desktop/Documents/Downloads、会话项目目录及 Codex 媒体目录收集已引用的现存文件；--include 扩展允许范围。不是全盘或整个项目递归备份，未解析引用、失效路径和复制失败要分别报告。跳过登录凭据、常见密钥、浏览器资料与依赖目录，但聊天文本本身仍可能含敏感信息。不要自动上传备份。

objects 按内容去重，snapshots 保留历史版本；支持硬链接的目标盘复用内容，不支持时退回复制。不要编辑备份文件。不硬链接实时来源，不自动删除源文件或旧快照。默认保留至少 15 GiB 空间，低于此值报告失败；不要擅自降低保留值或删除数据。

complete 仅表示捕获与日志覆盖没有已知错误，**不等于恢复已验证**。partial、非零退出或 failure.json 时说明缺项，上次 latest 指针保持不变。源文件复制时变化会报告问题；两个数据库是相邻时刻快照，正在执行的一轮不保证完整纳入。

首次、修复遗漏后和迁移前运行 verify --full，逐个读回 SHA-256。日常快速校验，每周一次完整校验。查看 summary.json、verification-*.json 与 last-run.json，不把仅有导出说明或哈希通过称为原会话恢复成功。

## 恢复验证

首次、Codex 升级或迁移前，读 [恢复说明](references/restore.md)。运行 scripts/restore_check.py --snapshot <快照路径>，在隔离 CODEX_HOME 中验证读取和 resume，不发新消息、不覆盖实时数据。区分接口加载、新一轮模型回复、新电脑桌面侧边栏三种不同结果。当前版本的实测不能保证其他 Codex 版本兼容。

## 定期备份

仅用户要求定期执行时设置调度；安装 skill 本身不自动新建任务。优先查已有同用途任务，避免重复。若 Codex automation_update 可用，按用户频率创建或更新本聊天 heartbeat，运行 scripts/daily_backup.py，使用明确的 --root 与 --source；时间遵循用户本地时区。没指定频率可建议每天 03:00，明确采用的频率。

Codex 自动任务依赖电脑、应用和账号可用；需要脱离 Codex 账号的调度时，按用户选择参考 [系统调度](references/scheduling.md)，不要同时暗增两套任务。daily_backup.py 不调用模型，运行备份、快速校验，周一增加完整校验。失败用非零退出报告。

## 交付

给出保存位置、会话/消息/普通与压缩日志数、文件数、校验状态、遗漏和实际调度。说明本地副本不等于云端聊天备份，不保证解封、跨账号恢复或所有版本一键迁移。同盘副本建议再另存一份到另一设备。
