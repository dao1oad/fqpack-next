# Codex 全局指令（AGENTS.md）

## 语言
- 默认使用简体中文回复（除非用户明确要求英文）。
- 代码、命令、文件路径、标识符保持原样（通常为英文）。

## 文档
- 项目文档优先中文；需要时在括号中保留关键英文术语。

## 风格
- 直接、简洁、可执行；避免空话。

## Git/GitHub
- 默认使用 SSH 远端（本项目）：`ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git`
- 如必须走 HTTPS 且需要代理，可按命令级别注入（示例）：`git -c http.proxy=http://127.0.0.1:10809 -c https.proxy=http://127.0.0.1:10809 <cmd>`
- 不要提交密钥/Token；`.env` 等敏感文件保持在 `.gitignore` 中。

## Skills（可选）
- 本环境支持在本机 Codex skills 目录下按需加载 `SKILL.md`，并遵循其中工作流。
- 若用户点名技能，或任务明显匹配技能描述，则优先使用该技能。
