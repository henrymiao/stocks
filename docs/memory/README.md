# Claude 记忆镜像（灾备副本）

本目录是 `~/.claude/projects/-Users-allglitter-codes-stocks/memory/` 的镜像，由
`tools/sync_memory_mirror.sh` 复制，随仓库自动提交推送到 GitHub 做异地备份。

- **真身在 live 目录**：这里的文件是只读副本，直接改动会在下次同步时被覆盖，也不会影响会话。
- **恢复方法**（换机/丢失时）：把本目录的 `*.md` 拷回上述 live 路径即可。
- 同步时机：每次复盘会话结束时执行（见 daily-review-protocol）。
