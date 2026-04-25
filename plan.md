# Agent设计架构计划

## Context

需要结合hermes-agent、openclaw和claw-code三个参考工程的架构分析，设计一个统一的agent架构。

**hermes-agent特点：**
- Python实现，自改进AI代理框架
- Context Engine模式（策略模式）处理上下文压缩
- 传输层适配器支持多LLM provider
- ACP协议适配器暴露能力给编辑器
- 多消息后端（Telegram, Discord等）

**openclaw特点：**
- TypeScript/Node.js实现，多通道AI网关
- 插件式模块化架构
- ACP协议用于多代理通信
- 配置驱动的安全策略

**claw-code特点：**
- Rust实现（~20K行，9个crate）
- CLI工具harness，高性能
- Trait抽象层（ApiClient, ToolExecutor）
- 显式PermissionPolicy引擎
- Registry模式管理全局状态
- 状态机管理Worker生命周期

---

## 架构设计计划

### 1. 核心架构分层

```
┌─────────────────────────────────────────┐
│           Channel/Transport Layer        │  消息通道接入（Telegram, Discord等）
├─────────────────────────────────────────┤
│              ACP Protocol               │  代理通信协议（会话、委派、事件）
├─────────────────────────────────────────┤
│           Agent Orchestration           │  Agent编排（子代理、并行化）
├─────────────────────────────────────────┤
│         Planning & Reasoning            │  规划推理（ReAct、任务分解、反思）
├─────────────────────────────────────────┤
│            Context Engine               │  上下文管理（压缩、摘要、记忆）
├─────────────────────────────────────────┤
│         Transport Adapter Layer          │  LLM传输适配（Anthropic, OpenAI等）
├─────────────────────────────────────────┤
│            Long-term Memory             │  长期记忆（向量存储、语义检索）
├─────────────────────────────────────────┤
│            Observability                │  可观测性（日志、Tracing、指标）
├─────────────────────────────────────────┤
│            Skill System                 │  技能系统（程序化记忆）
└─────────────────────────────────────────┘
```

### 2. 关键组件设计

#### 2.1 Context Engine（继承hermes-agent）
- **接口**: `ContextEngine` ABC
- **实现**: `ContextCompressor` - 基于token预算的摘要压缩
- **扩展点**: 未来可替换为LCM压缩器

#### 2.2 Transport Adapter（继承hermes-agent）
- 统一接口：`TransportAdapter` (trait)
- 实现类：`AnthropicTransport`, `OpenAITransport`, `BedrockTransport`
- 响应标准化：`NormalizedResponse`

#### 2.3 ACP Protocol（借鉴openclaw + hermes-agent）
- 会话管理：`SessionManager`
- 事件系统：工具调用、思考中、步骤完成、消息流
- 权限桥接：权限审批回调

#### 2.4 Plugin System（借鉴openclaw + claw-code）
- 插件加载器：`PluginLoader`
- 注册表：`PluginRegistry`
- 清单：`PluginManifest`
- 运行时：`PluginRuntime`
- **Registry模式**: 全局注册表管理Task/MCP/LSP/Team/Cron

#### 2.5 Channel System（继承openclaw）
- 通道插件接口
- 消息翻译：`MessageTranslator`
- 事件桥接

#### 2.6 Permission System（借鉴claw-code）
- `PermissionPolicy` trait - 权限策略抽象
- `PermissionMode` - 模式枚举（ReadOnly, WorkspaceWrite, DangerFullAccess, Prompt）
- `PermissionEnforcer` - 强制执行层
- **策略引擎**: allow/deny/ask规则评估

#### 2.7 Worker Lifecycle（借鉴claw-code）
- 状态机：`WorkerStatus`
- 状态转换：`Spawning` -> `TrustRequired` -> `ReadyForPrompt` -> `Running` -> `Finished/Failed`
- 启动信任机制、重试逻辑

#### 2.8 Self-Improvement System（继承hermes-agent）
- **技能创建**: 从经验中自动创建技能
- **技能改进**: 在使用中持续优化技能
- **跨会话召回**: 搜索历史对话实现记忆
- **用户建模**: Honcho dialectic风格的用户偏好学习
- **技能清单**: `SkillManifest` 定义技能规格
- **技能执行器**: `SkillExecutor` 运行技能代码

#### 2.9 Agent Harness（借鉴claw-code）
- **CLI Harness**: 命令行入口，REPL和单次prompt模式
- **API Harness**: API服务器模式
- **HarnessConfig**: 多源配置加载（user > project > local）
- **工具执行环境**: ToolExecutor trait抽象
- **沙箱支持**: Bash执行、Docker、SSH隔离
- **Session管理**: JSONL格式持久化，会话压缩、分支

#### 2.10 Planning & Reasoning（新增）
- **ReAct循环**: Think -> Act -> Observe -> Answer
- **任务分解**: TaskDecomposer分解复杂任务为子任务
- **步骤排序**: TopologicalSort子任务依赖排序
- **执行监控**: ExecutionMonitor跟踪进度，处理失败
- **自我验证**: SelfVerifier验证输出正确性
- **反思机制**: Reflector从错误中学习

#### 2.11 Long-term Memory（新增）
- **向量存储**: VectorStore trait抽象，支持多种后端
- **语义检索**: SemanticSearch检索相关记忆
- **记忆索引**: MemoryIndexer自动索引新记忆
- **记忆衰减**: MemoryDecay管理记忆生命周期
- **用户画像**: UserProfile存储用户偏好和历史

#### 2.12 Observability（新增）
- **结构化日志**: StructuredLogger记录所有操作
- **Tracing**: OpenTelemetry集成分布式追踪
- **指标收集**: MetricsCollector (token使用、成本、延迟)
- **Debug接口**: DebugServer支持实时调试
- **审计日志**: AuditLog记录敏感操作

#### 2.13 Agent Core Loop（核心缺失）
- **AgentLoop**: 主执行循环，协调所有组件
  ```
  Loop (max_iterations保护):
    1. 构建ApiRequest (system_prompt + messages)
    2. ApiClient.stream() 调用LLM
    3. 解析AssistantEvent响应
    4. 提取pending_tool_uses
    5. if 无工具调用 → break (完成)
    6. for each tool:
       6.1 PreToolUse Hook
       6.2 PermissionPolicy.authorize()
       6.3 ToolExecutor.execute()
       6.4 PostToolUse Hook
       6.5 保存tool_result到session
    7. 继续Loop
    8. MaybeAutoCompact (自动压缩)
  ```
- **call_depth**: 防止无限递归
- **max_iterations**: 最大迭代次数保护
- **Session**: 消息历史、会话压缩状态

#### 2.14 Bootstrap & Initialization（运行时必需）
- **Bootstrap**: Agent启动流程
  ```
  1. 加载配置文件(.claw.json)
  2. 初始化Logger
  3. 初始化Registry（Task/MCP/LSP/Team）
  4. 初始化Transport Adapter
  5. 连接LLM Provider
  6. 加载工具注册表
  7. 恢复或创建Session
  8. 进入AgentLoop
  ```
- **Shutdown**: 优雅关闭流程，保存状态

#### 2.15 Message Protocol（运行时必需）
- **Message格式**:
  ```json
  {
    "id": "uuid",
    "type": "user|assistant|tool_call|tool_result|system",
    "content": "string",
    "metadata": { "timestamp", "channel", "user_id" },
    "attachments": [{ "type", "path", "data" }]
  }
  ```
- **MessageQueue**: 消息队列管理
- **ConversationContext**: 多轮对话上下文追踪

#### 2.16 Tool Registry（运行时必需）
- **ToolRegistry**: 全局工具注册表
  ```rust
  trait ToolRegistry {
    fn register(&mut self, tool: ToolSpec) -> Result<()>;
    fn get(&self, name: &str) -> Option<ToolSpec>;
    fn list(&self) -> Vec<ToolSpec>;
    fn execute(&self, name: &str, input: &str) -> Result<String>;
  }
  ```
- **内置工具集**: bash, read_file, write_file, edit_file, glob_search, grep_search, web_search, web_fetch
- **工具发现**: 插件自动发现机制

#### 2.17 Configuration Schema（运行时必需）
- **AgentConfig**:
  ```json
  {
    "version": "1.0",
    "agent": { "name", "model", "temperature", "max_tokens" },
    "providers": [{ "type", "api_key", "base_url" }],
    "tools": { "enabled": [], "disabled": [], "custom": [] },
    "permissions": { "mode": "read_only|workspace_write|danger_full_access" },
    "channels": [{ "type", "config" }],
    "plugins": [{ "name", "config" }]
  }
  ```
- **配置优先级**: CLI args > 环境变量 > 项目配置 > 用户配置 > 默认值

#### 2.18 Message Queue & Event Bus
- **EventBus**: 事件总线，组件间通信
- **事件类型**: `UserMessage`, `ToolCall`, `ToolResult`, `LlmResponse`, `Error`, `SystemEvent`
- **EventHandler**: 事件处理器注册表
- **异步队列**: 优先级队列处理延迟消息

#### 2.19 State Management
- **AgentState**: Agent状态容器
  - `flags`: 状态标志（running, paused, interrupted）
  - `variables`: 用户定义的变量
  - `call_depth`: 当前调用深度
  - `iteration`: 当前迭代数
  - `start_time`: 开始时间
- **StateSnapshot**: 状态快照用于恢复
- **StateValidator**: 状态验证器

#### 2.20 Error Handling
- **Error分类**: ToolError, ApiError, TimeoutError, PermissionError, ValidationError
- **RecoveryStrategy**: 错误恢复策略（retry, fallback, abort, escalate）
- **ErrorClassifier**: 错误分类决定处理方式
- **CircuitBreaker**: 熔断器防止级联失败
- **RetryPolicy**: 指数退避、jitter、最大重试次数

#### 2.21 Task Verification（优秀agent必需）
- **TaskVerifier**: 验证任务是否真正完成
  - 用户目标提取
  - 完成度检查
  - 缺失项识别
- **QualityScore**: 任务质量评分
- **CompletionCriteria**: 完成标准定义

#### 2.22 Cost Control（优秀agent必需）
- **TokenBudget**: Token预算管理
  - per-turn限制
  - per-session限制
  - 预算警告阈值
- **CostTracker**: 成本跟踪
  - provider定价
  - 当前成本累计
  - 成本异常检测
- **RateLimiter**: API限流
  - 请求频率限制
  - 并发数控制
  - 队列管理

#### 2.23 Interactive Debugging（优秀agent必需）
- **DebugServer**: 实时调试接口
  - 断点设置
  - 变量检查
  - 单步执行
  - 调用栈查看
- **DebugClient**: CLI调试客户端
- **SessionReplayer**: 会话重放调试

### 3. 设计模式应用

| 模式 | 来源 | 应用 |
|------|------|------|
| 策略模式 | hermes-agent | ContextEngine可插拔压缩策略 |
| 适配器模式 | hermes-agent | Transport Layer统一多LLM接口 |
| 工厂模式 | hermes-agent | SessionManager创建Agent实例 |
| 观察者模式 | hermes-agent | AIAgent回调事件系统 |
| 模板方法 | hermes-agent | ContextCompressor压缩算法骨架 |
| 插件模式 | openclaw | Channel/Extension扩展能力 |
| Registry模式 | claw-code | 全局单例访问（Task/MCP/LSP/Team/Cron） |
| 状态机模式 | claw-code | Worker生命周期状态转换 |
| 策略引擎模式 | claw-code | PermissionPolicy allow/deny/ask规则 |
| Trait抽象 | claw-code | ApiClient, ToolExecutor定义接口 |

### 4. 关键文件

```
src/
├── agent/                    # 核心Agent实现
│   ├── context_engine.py    # 上下文管理接口（ContextEngine ABC）
│   ├── context_compressor.py # 默认压缩实现（token预算+摘要）
│   └── transports/          # LLM传输适配层（Trait抽象）
├── acp/                      # ACP协议实现
│   ├── server.py            # ACP服务器
│   ├── session.py           # 会话管理
│   └── events.py            # 事件系统
├── runtime/                  # 运行时核心
│   ├── conversation.rs      # ConversationRuntime核心循环
│   ├── session.rs           # 会话持久化（JSONL格式）
│   ├── permissions.rs       # PermissionPolicy权限系统
│   ├── config.rs            # 多源配置加载
│   └── worker_boot.rs       # Worker状态机
├── plugins/                  # 插件系统
│   ├── loader.py
│   ├── registry.py          # PluginRegistry注册表
│   └── runtime.py
├── channels/                 # 通道系统
│   └── base.py
├── tools/                    # 工具系统
│   └── spec.rs              # 工具规格定义
├── skills/                   # 技能系统（自改进）
│   ├── manifest.rs          # SkillManifest技能清单
│   ├── executor.rs          # SkillExecutor技能执行器
│   ├── learner.rs           # SkillLearner从经验学习
│   └── memory.rs            # 跨会话记忆
├── harness/                  # Agent Harness
│   ├── cli.rs               # CLI入口（REPL/单次prompt）
│   ├── api.rs               # API服务器Harness
│   └── config.rs            # HarnessConfig配置
├── planning/                  # 规划推理
│   ├── react.rs             # ReAct循环
│   ├── decomposer.rs        # 任务分解器
│   ├── monitor.rs           # 执行监控器
│   ├── verifier.rs          # 自我验证器
│   └── reflector.rs         # 反思机制
├── memory/                    # 长期记忆
│   ├── vector.rs            # VectorStore向量存储
│   ├── search.rs            # SemanticSearch语义检索
│   ├── indexer.rs           # MemoryIndexer索引
│   └── decay.rs             # MemoryDecay衰减
├── observability/             # 可观测性
│   ├── logger.rs            # StructuredLogger
│   ├── tracing.rs           # OpenTelemetry集成
│   ├── metrics.rs           # MetricsCollector
│   └── debug.rs             # DebugServer
├── core/                      # 核心运行时
│   ├── loop.rs              # AgentLoop主执行循环
│   ├── bootstrap.rs         # Bootstrap启动流程
│   ├── shutdown.rs          # Shutdown优雅关闭
│   ├── state.rs             # AgentState状态管理
│   ├── event_bus.rs         # EventBus事件总线
│   ├── message.rs           # MessageProtocol消息格式
│   ├── error.rs             # ErrorHandling错误处理
│   └── recovery.rs          # RecoveryStrategy恢复策略
├── config/                    # 配置系统
│   ├── schema.rs           # AgentConfig配置Schema
│   ├── loader.rs           # ConfigLoader配置加载
│   └── resolver.rs         # ConfigResolver优先级解析
├── tools/                    # 工具系统（完善）
│   ├── registry.rs         # ToolRegistry工具注册表
│   ├── spec.rs             # ToolSpec工具规格
│   ├── executor.rs         # ToolExecutor执行器
│   └── builtin/            # 内置工具集
│       ├── bash.rs
│       ├── file_ops.rs
│       └── search.rs
└── sandbox/                  # 沙箱执行
    ├── bash.rs              # Bash沙箱
    ├── docker.rs            # Docker沙箱
    └── ssh.rs               # SSH远程沙箱
```

### 5. 实现步骤

1. **Phase 1: 核心框架 + Agent Loop**
   - 定义ContextEngine ABC接口
   - 实现ContextCompressor压缩算法
   - 创建Transport Adapter基础结构
   - Trait抽象定义（ApiClient, ToolExecutor）
   - **AgentLoop主执行循环实现**
   - **call_depth和max_iterations保护**

2. **Phase 2: 运行时必需组件**
   - **Bootstrap启动流程**
   - **Message Protocol消息格式**
   - **Tool Registry工具注册表**
   - **内置工具集（bash/file/search）**
   - **Configuration Schema**
   - **Config Loader**

3. **Phase 3: ACP协议**
   - SessionManager会话管理
   - ACP事件系统
   - 权限桥接

4. **Phase 4: 插件系统**
   - PluginLoader/Registry
   - PluginManifest解析
   - 运行时沙箱

5. **Phase 5: 通道集成**
   - 通道插件接口
   - 消息翻译层

6. **Phase 6: Agent Harness**
   - CLI Harness（REPL/单次prompt）
   - API Harness（服务器模式）
   - 多源配置加载
   - 工具执行环境
   - 沙箱执行（Bash/Docker/SSH）

7. **Phase 7: 自改进系统**
   - SkillManifest技能清单定义
   - SkillExecutor技能执行器
   - SkillLearner从经验学习
   - 跨会话记忆系统
   - 用户偏好建模

8. **Phase 8: 规划推理**
   - ReAct循环实现
   - TaskDecomposer任务分解
   - ExecutionMonitor执行监控
   - SelfVerifier自我验证
   - Reflector反思机制

9. **Phase 9: 长期记忆**
   - VectorStore向量存储抽象
   - SemanticSearch语义检索
   - MemoryIndexer记忆索引
   - MemoryDecay记忆衰减
   - UserProfile用户画像

10. **Phase 10: 可观测性**
    - StructuredLogger结构化日志
    - OpenTelemetry tracing集成
    - MetricsCollector指标收集
    - DebugServer调试接口
    - AuditLog审计日志

11. **Phase 11: 核心运行时完善**
    - EventBus事件总线实现
    - AgentState状态管理
    - ErrorHandling统一错误处理
    - RecoveryStrategy恢复策略（指数退避）
    - CircuitBreaker熔断器

12. **Phase 12: 优秀agent组件**
    - TaskVerifier任务验证
    - TokenBudget成本控制
    - CostTracker成本跟踪
    - RateLimiter限流
    - DebugServer实时调试

13. **Phase 13: 集成测试**
    - 端到端测试
    - 工具调用测试
    - 多轮对话测试
    - 错误恢复测试
    - 成本控制测试
    - 调试功能测试

### 6. 验证方案

- 单元测试：各模块独立测试
- 集成测试：端到端消息流测试
- 压缩验证：对比压缩前后token计数
- 多provider测试：Anthropic/OpenAI/Bedrock轮询
- 插件隔离测试：验证沙箱边界
- Harness测试：CLI和API模式功能测试
- 自改进验证：技能创建/改进/召回流程测试
- 通道集成测试：多消息平台收发测试
- 规划推理测试：ReAct循环、任务分解执行
- 长期记忆测试：向量检索、记忆召回准确率
- 可观测性测试：日志完整性、tracing链路
- **核心循环测试**: AgentLoop执行、call_depth保护、timeout机制
- **错误处理测试**: ErrorHandling、RecoveryStrategy、CircuitBreaker
- **端到端测试**: 完整agent任务执行（多轮对话+工具调用）

---

## 参考来源

- hermes-agent: ref/hermes-agent/ (Python, Nous Research, 自改进框架)
- openclaw: ref/openclaw/ (TypeScript, 多通道网关)
- claw-code: ref/claw-code/ (Rust, UltraWorkers, CLI工具)

### 总结文件

- [hermes-agent.md](ref/hermes-agent/hermes-agent.md)
- [openclaw.md](ref/openclaw/openclaw.md)
- [claw-code.md](ref/claw-code/claw-code.md)
