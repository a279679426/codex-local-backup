# codex-local-backup

[下载 v1.0.0 安装包](https://github.com/a279679426/codex-local-backup/releases/download/v1.0.0/codex-local-backup-v1.0.0.zip) · [查看 Releases](https://github.com/a279679426/codex-local-backup/releases)

可分发的本地会话备份 skill。仅代码和文档，不包含作者聊天、附件、用户名或登录凭据。MIT 许可。

## 安装

解压 ZIP，将整个 codex-local-backup 文件夹放进当前用户的 `$CODEX_HOME/skills/`；未设置 CODEX_HOME 时放进 `~/.codex/skills/`。Windows 默认对应用户目录下 `.codex\skills\`。若已有同名 skill，先保留原版本再替换。重新打开聊天使其发现新技能。

也可把解压后的文件夹交给 Codex：

> 请阅读这个文件夹的 SKILL.md，把 codex-local-backup 安装到我的技能目录。先检查 Python 和本机 Codex 存储情况，不上传数据、不改动原始会话。

## 使用

> 使用 $codex-local-backup，把这台电脑上已有的本地 Codex 会话备份到我指定的文件夹。保留压缩 session、生成可读聊天，校验后明确报告遗漏。

> 用 $codex-local-backup 检查备份，并在隔离目录验证原会话能否加载。不要发新消息，不覆盖当前数据。

> 用 $codex-local-backup 设置每天一次备份，保存到这个目录。先检查已有计划，告诉我采用 Codex 自动任务还是系统调度，以及它依赖哪些运行条件。

脚本可直接运行：

```sh
python3 <skill目录>/scripts/backup.py backup --root <备份目标目录>
python3 <skill目录>/scripts/backup.py verify --root <备份目标目录> --full
python3 <skill目录>/scripts/restore_check.py --snapshot <备份目标目录>/snapshots/<快照名>
```

Python 3.10+，没有 python3 命令的 Windows 使用 py -3。默认来源 CODEX_HOME / ~/.codex，默认目标 ~/CodexBackups。自定义来源用 --source，自定义引用文件范围用可重复的 --include。压缩日志文本导出回退需要 Python 3.14+ 或 zstd 命令；缺少时仍保留压缩原文件，并报告导出缺项。

## 范围与验证

- 支持普通/压缩日志、存在的版本化会话数据库、可读 Markdown、关联文件尽力收集、去重历史快照和文件哈希。
- 自动识别数据库数字版本，但内部存储格式仍可能变化；遇到未知 schema 报告 partial，不能承诺所有版本兼容。
- 备份默认不上传、不删除历史、不含 auth.json；聊天原文和代码仍可能含敏感内容，不要把自己的备份目录上传到公共仓库。
- 关联文件不是全盘或完整项目备份；要保留环境、Git 未跟踪文件与全部素材，应另行备份项目目录。
- macOS 进行了真实会话测试；Windows/Linux 尚未实机验证，不宣称全平台都已验证。
- 同盘备份不防硬盘故障。复制整个备份目录到另一设备；硬链接在复制后可能展开、占用更多空间。
- 恢复接口通过不代表跨版本、跨账号或新电脑桌面一键恢复；实际新一轮模型回复仍须在迁移目标上验证。

## 运行测试

`python3 <skill目录>/scripts/test_backup.py`

这些测试只使用临时合成数据，不读取个人会话。安装本身不创建定时任务。定期脚本可由系统调度执行，详情见 references/scheduling.md。
