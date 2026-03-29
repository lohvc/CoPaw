# Session Report Heartbeat Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-platform `copaw session-skill-report` command that can be invoked from `HEARTBEAT.md` without changing CoPaw's heartbeat runtime flow.

**Architecture:** Move the existing standalone script logic into a package module under `copaw`, expose a pure `run()` entrypoint plus a CLI command, and keep the heartbeat integration prompt-level only by updating the default `HEARTBEAT.md` template text. Cross-platform compatibility comes from using the installed `copaw` command first and `python -m ...` only as fallback guidance in the template, not from shell-specific wrappers.

**Tech Stack:** Python 3.10+, Click CLI, pathlib, stdlib networking/process APIs, pytest

---

### Task 1: Add failing tests for the session report module

**Files:**
- Create: `tests/unit/app/test_session_skill_report.py`
- Modify: `src/copaw/app/session_skill_report.py`

- [ ] **Step 1: Write the failing tests for parser defaults and summary output shape**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/app/test_session_skill_report.py -v`
Expected: FAIL because `copaw.app.session_skill_report` does not exist yet.

- [ ] **Step 3: Write minimal implementation module with importable API**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/app/test_session_skill_report.py -v`
Expected: PASS

### Task 2: Add failing tests for the CLI command

**Files:**
- Create: `tests/unit/cli/test_cli_session_skill_report.py`
- Modify: `src/copaw/cli/main.py`
- Create: `src/copaw/cli/session_skill_report_cmd.py`

- [ ] **Step 1: Write the failing CLI tests**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/cli/test_cli_session_skill_report.py -v`
Expected: FAIL because `session-skill-report` is not registered.

- [ ] **Step 3: Add the lazy CLI command wiring and command module**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/cli/test_cli_session_skill_report.py -v`
Expected: PASS

### Task 3: Update default heartbeat templates

**Files:**
- Modify: `src/copaw/app/routers/agents.py`
- Modify: `src/copaw/agents/md_files/zh/HEARTBEAT.md`
- Modify: `src/copaw/agents/md_files/en/HEARTBEAT.md`
- Modify: `src/copaw/agents/md_files/ru/HEARTBEAT.md`

- [ ] **Step 1: Write the failing tests for seeded default heartbeat content**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/workspace/test_agent_creation.py -v`
Expected: FAIL after adding assertions for the new heartbeat guidance.

- [ ] **Step 3: Update seeded heartbeat content to instruct the agent to run `copaw session-skill-report` first and fall back to `python -m copaw.app.session_skill_report`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/workspace/test_agent_creation.py -v`
Expected: PASS

### Task 4: Verify targeted end-to-end behavior

**Files:**
- Test: `tests/unit/app/test_session_skill_report.py`
- Test: `tests/unit/cli/test_cli_session_skill_report.py`
- Test: `tests/unit/workspace/test_agent_creation.py`

- [ ] **Step 1: Run the targeted suite**

Run: `pytest tests/unit/app/test_session_skill_report.py tests/unit/cli/test_cli_session_skill_report.py tests/unit/workspace/test_agent_creation.py -v`
Expected: PASS

- [ ] **Step 2: Review for platform assumptions**

Check:
- No hardcoded desktop paths
- No `python3`-only invocation in templates
- No shell chaining assumptions

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-03-29-session-report-heartbeat-command.md tests/unit/app/test_session_skill_report.py tests/unit/cli/test_cli_session_skill_report.py tests/unit/workspace/test_agent_creation.py src/copaw/app/session_skill_report.py src/copaw/cli/main.py src/copaw/cli/session_skill_report_cmd.py src/copaw/app/routers/agents.py src/copaw/agents/md_files/zh/HEARTBEAT.md src/copaw/agents/md_files/en/HEARTBEAT.md src/copaw/agents/md_files/ru/HEARTBEAT.md
git commit -m "feat: add session report heartbeat command"
```
