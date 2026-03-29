---
summary: "HEARTBEAT.md 工作区模板"
read_when:
  - 手动引导工作区
---

# HEARTBEAT.md

# 每次 heartbeat 开始时，先执行 `copaw session-skill-report`。

# 如果 `copaw` 命令不可用，再执行 `python -m copaw.app.session_skill_report`。

# 必须解析命令输出的 JSON 摘要，不要只看退出码。

# 保持此文件为空（或只有注释）可跳过 heartbeat API 调用。

# 想让 agent 定期检查什么，就在下面加任务。
