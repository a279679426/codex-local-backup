# 恢复验证与迁移

先运行 codex --version，确认 CLI 在 PATH 中。备份原始目录应包含全部 session 文件（含 .jsonl.zst）及当时存在的会话数据库。数据库有可读历史，不代表缺失原始 rollout 时还能恢复。

运行 `python3 <skill-dir>/scripts/restore_check.py --snapshot <快照目录>`。脚本会在临时独立 CODEX_HOME 中复制记录，重写恢复副本的 threads.rollout_path，然后用当前 Codex app-server 的 thread/read、thread/turns/list、thread/resume 测试。仅在测试副本取消归档；不调用 turn/start、不复制登录凭据、不修改正在使用的数据。退出时清理临时目录。macOS 优先 APFS clonefile，其余环境有足够空间才复制；Codex CLI 不存在或协议不同则报告失败。

看 restore-check.json 的逐项结果及 scope，不能把线程加载成功写成已验证真实回复或桌面侧边栏恢复。跨机迁移还需调整项目 cwd 和附件路径、恢复实际文件、登录可用账号。先在独立数据目录测试，保留新电脑已有数据，不直接覆盖 ~/.codex。某些旧版本不支持当前分页接口，需要按版本另行检查。

macOS 真实会话验证通过；Windows/Linux 使用了兼容代码，尚未在真实设备验证。跨版本兼容不保证。

官方参考：https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread
