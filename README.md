# kiwiclaw Agent Framework

模块化 AI Agent 系统，支持多工具调用、长期记忆、技能学习和可观测性。

## 快速开始

### 安装依赖

```bash
cd agent_framework
pip install -r requirements.txt
```

### 配置环境变量

创建 `.env` 文件：

```bash
ANTHROPIC_API_KEY=your_api_key_here
MODEL_ID=claude-sonnet-4-20250514  # 可选，默认 claude-sonnet-4-20250514
```

### 运行 Agent

**单次 Prompt 模式：**

```bash
python -m agent_framework.cli.main run "帮我写一个 Hello World 程序"
```

**交互式 REPL 模式：**

```bash
python -m agent_framework.cli.main shell
```

**查看可用工具：**

```bash
python -m agent_framework.cli.main tool-list
```

## Agent 模式

Agent 支持四种工作模式，通过 `--mode` 参数指定：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `simple` | 快速回答，简单任务 | 简单问答、文件操作 |
| `deep` | 深度思考，分析原理和步骤 | 技术问题分析、代码审查 |
| `plan` | 制定详细计划 | 复杂任务分解、项目规划 |
| `debug` | 三现两原原则调试 | 问题诊断、错误排查 |

**示例：**

```bash
python -m agent_framework.cli.main run --mode plan "部署一个 Web 应用"
```

## 内置工具

Agent 配备以下内置工具：

### 文件操作

| 工具 | 说明 | 参数 |
|------|------|------|
| `read_file` | 读取文件内容 | `path`, `limit`(可选) |
| `write_file` | 写入文件 | `path`, `content` |
| `edit_file` | 编辑文件（替换文本） | `path`, `old_text`, `new_text` |
| `bash` | 执行 Shell 命令 | `command` |

### 任务管理

| 工具 | 说明 | 参数 |
|------|------|------|
| `TodoWrite` | 更新待办列表 | `items` |
| `task_create` | 创建任务 | `subject`, `description` |
| `task_get` | 获取任务详情 | `task_id` |
| `task_update` | 更新任务状态 | `task_id`, `status` |
| `task_list` | 列出所有任务 | - |

### 后台任务

| 工具 | 说明 | 参数 |
|------|------|------|
| `background_run` | 后台执行命令 | `command`, `timeout` |
| `check_background` | 检查后台任务 | `task_id` |

### Web 工具

| 工具 | 说明 | 参数 |
|------|------|------|
| `web_search` | 搜索互联网 | `query`, `num_results` |
| `web_fetch` | 获取网页内容 | `url`, `max_chars` |

### 其他

| 工具 | 说明 | 参数 |
|------|------|------|
| `text_to_image` | 生成图片 | `prompt`, `aspect_ratio`, `output_path` |
| `compress` | 压缩上下文 | - |

## 技能系统 (Skills)

Agent 支持通过技能扩展能力。技能存放在 `agent_framework/skills/` 目录。

### 创建技能

创建目录结构：

```
skills/
└── my-skill/
    └── SKILL.md
```

`SKILL.md` 格式：

```markdown
---
name: my-skill
description: 我的自定义技能
---

# 我的自定义技能

这里是技能描述和使用说明。
技能代码或配置内容...
```

### 使用技能

技能内容会自动加载到 Agent 的 system prompt 中。

## 记忆系统 (Memory)

Agent 具有长期记忆能力：

- **向量存储**：存储记忆条目
- **语义搜索**：根据语义相关性检索记忆

### 保存记忆

```python
agent.save_memory("用户喜欢使用 dark mode", metadata={"type": "preference"})
```

### 检索记忆

```python
memory = agent.get_relevant_memories("用户界面偏好")
```

## 沙箱模式

使用 `--sandbox` 参数在 Docker 容器中执行工具，确保安全隔离：

```bash
python -m agent_framework.cli.main run --sandbox "执行危险命令"
```

## 编程接口

### 基本使用

```python
from agent_framework.core import Agent, AgentConfig
import asyncio

async def main():
    config = AgentConfig(
        name="my-agent",
        model="claude-sonnet-4-20250514",
        mode="simple"
    )
    agent = Agent(config=config)

    result = await agent.think("帮我写一个 Python 快速排序")
    print(result)

asyncio.run(main())
```

### 获取系统提示

```python
system_prompt = agent.get_system_prompt()
```

### 记忆集成

```python
# 保存记忆
agent.save_memory("关键信息", metadata={"source": "user"})

# 检索相关记忆
relevant = agent.get_relevant_memories("之前保存了什么")
```

## 配置选项

### AgentConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | "agent" | Agent 名称 |
| `model` | str | claude-sonnet-4-20250514 | 模型 ID |
| `mode` | str | "simple" | 工作模式 |
| `sandbox_enabled` | bool | False | 是否启用沙箱 |
| `permission_mode` | str | "danger_full_access" | 权限模式 |

### 权限模式

| 模式 | 说明 |
|------|------|
| `read_only` | 只读模式，限制写入操作 |
| `workspace_write` | 允许工作区写入 |
| `danger_full_access` | 允许所有操作 |

### 环境变量

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 |
| `ANTHROPIC_BASE_URL` | API 基础 URL（可选） |
| `MODEL_ID` | 模型 ID（默认 claude-sonnet-4-20250514） |

## 项目结构

```
agent_framework/
├── core/               # 核心 Agent 实现
│   ├── __init__.py    # Agent, Tool, ToolRegistry
│   ├── bootstrap.py   # 启动初始化
│   ├── state.py       # 状态管理
│   └── transports/    # LLM 传输适配
├── cli/               # 命令行接口
│   └── main.py        # CLI 入口
├── observability/     # 可观测性
│   ├── tracing.py     # 分布式追踪
│   ├── metrics.py     # 指标收集
│   └── hooks.py       # 钩子系统
├── skills/            # 技能系统
├── memory/            # 长期记忆
├── acp/               # ACP 协议
├── sandbox/          # 沙箱执行
└── planning/          # 规划推理
```

## 数据流

```
用户输入
    ↓
Bootstrap 初始化
    ├── Tracing (追踪)
    ├── Hooks (钩子)
    ├── StateManager (状态)
    └── Permission (权限)
    ↓
Agent.think() 循环
    ├── 上下文压缩
    ├── LLM 调用
    ├── 工具执行
    │   ├── Pre-Hook
    │   ├── 权限检查
    │   ├── 工具处理
    │   └── Post-Hook
    └── 响应返回
```

## 架构设计

本框架参考以下优秀项目设计：

- **hermes-agent**: Context Engine、传输适配器、技能系统
- **openclaw**: 插件架构、钩子系统
- **claw-code**: 权限策略、状态管理、CLI Harness

详见 [plan.md](plan.md)。
