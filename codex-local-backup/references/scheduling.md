# 定期备份

优先尊重用户选择的调度方式。不要把“安装 skill”理解为同意创建后台计划。

## Codex 内的自动任务

有 automation_update 时可设置用户要求的 heartbeat，prompt 指向安装后的 SKILL.md，运行 daily_backup.py，显式传目标 --root。使用本地时区。日常快速检查，周一完整哈希校验。先查重再创建；依赖应用与账号可用，不能承诺封号后仍运行。

## 独立于 Codex 账号的系统计划

用户选择系统级调度后，先解析 Python 解释器、skill、备份目标的实际绝对路径，用系统本地时区；先手动成功执行一次以下命令，再登记计划：

`<python绝对路径> <skill目录>/scripts/daily_backup.py --root <备份目录>`

macOS：launchd 用户 LaunchAgent，ProgramArguments 用数组逐个填写路径，StartCalendarInterval 设置 Hour/Minute，标准输出和错误写到用户可访问的日志目录；不把带空格路径拼成 shell 命令，不要求唤醒或开机自动登录。系统休眠时的实际执行时机须核实，不保证准点。

Linux：用户 systemd timer 或 crontab，按当前环境选一个；使用绝对解释器路径与规范转义，保留标准输出/错误日志。先检查已有同名计划，不用未经审查的 curl|sh，不需要 root。

Windows：任务计划程序设置每天触发，程序填 Python 的绝对路径，参数填脚本及 --root，正确引用有空格路径。先手动运行并检查退出码，按用户选择登录条件；不要保存或索取密码。没有完成系统登记时只能说已给出配置，不能说已开启。

上述命令只调用本地 Python 脚本，不需要 Codex 登录或模型 API；首次恢复验证仍需要已安装的 Codex CLI。
