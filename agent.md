# Agent 推理架构对比分析

## 参考工程 vs 我们的 Agent

---

## 三个工程的推理详细代码逻辑

---

## 1. Hermes-Agent (Python) - 推理循环

### 核心循环 `run_agent.py`

```python
# 约第 8417 行
def run_conversation(self, user_message: str, ...) -> Dict[str, Any]:
    """主推理循环"""

    # 1. 初始化/重置各种重试计数器
    self._invalid_tool_retries = 0
    self._invalid_json_retries = 0
    self._empty_content_retries = 0
    self._incomplete_scratchpad_retries = 0
    self._codex_incomplete_retries = 0
    self._thinking_prefill_retries = 0

    # 2. 构建系统提示词（缓存机制）
    if self._cached_system_prompt is None:
        self._cached_system_prompt = self._build_system_prompt(system_message)

    # 3. 添加用户消息
    messages.append({"role": "user", "content": user_message})

    # 4. 迭代主循环
    iteration_budget = IterationBudget(self.max_iterations)

    while True:
        iterations += 1

        # 4.1 检查迭代预算
        if not iteration_budget.consume():
            return "max iterations reached"

        # 4.2 自动压缩检查
        if self._should_compress():
            self._compress_context()

        # 4.3 构建 API 请求
        request = self._build_api_request(
            system_prompt=self._cached_system_prompt,
            messages=messages
        )

        # 4.4 调用 LLM
        try:
            response = self._call_llm(request)
        except APIError as e:
            # 错误分类
            classified = classify_api_error(e)

            if classified.should_retry:
                # 指数退避重试
                sleep_time = jittered_backoff(self._retry_count)
                time.sleep(sleep_time)
                continue
            else:
                return f"API error: {e}"

        # 4.5 解析响应
        assistant_message = response.assistant_message

        # 4.6 提取工具调用
        pending_tool_uses = self._extract_tool_uses(assistant_message)

        if not pending_tool_uses:
            # 无工具调用 = 完成
            return assistant_message.text

        # 4.7 工具执行循环
        for tool_use in pending_tool_uses:
            # Pre-tool hook
            pre_result = self._run_pre_tool_hook(tool_use)

            # 权限检查
            if not self._check_permission(tool_use):
                result = "[PERMISSION DENIED]"
                self._record_tool_result(tool_use, result, is_error=True)
                continue

            # 执行工具
            try:
                result = self._execute_tool(tool_use)
            except ToolError as e:
                result = f"[TOOL ERROR] {e}"
                self._record_tool_result(tool_use, result, is_error=True)

                # Post-tool failure hook
                self._run_post_tool_failure_hook(tool_use, result)
                continue

            # Post-tool hook
            post_result = self._run_post_tool_hook(tool_use, result)
            if post_result.is_denied():
                result = "[HOOK DENIED]"

            # 记录结果
            self._record_tool_result(tool_use, result)

        # 4.8 将工具结果加入消息
        messages.append(self._build_assistant_message(assistant_message))
        messages.append(self._build_tool_results_message(tool_results))
```

### 错误分类 `agent/error_classifier.py`

```python
class FailoverReason(Enum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    FATAL_ERROR = "fatal_error"
    INVALID_TOOL = "invalid_tool"
    # ...

class RecoveryAction(Enum):
    RETRY = "retry"           # 重试当前方法
    RETRY_WITH_BACKOFF = "retry_with_backoff"  # 退避后重试
    FALLBACK = "fallback"     # 切换到备用方案
    ABORT = "abort"           # 直接终止

def classify_api_error(error: Exception) -> ClassifiedError:
    """错误分类"""
    if isinstance(error, RateLimitError):
        return ClassifiedError(
            reason=FailoverReason.RATE_LIMIT,
            should_retry=True,
            recovery=RecoveryAction.RETRY_WITH_BACKOFF,
            suggestion="Rate limited. Wait before retry."
        )
    elif isinstance(error, TimeoutError):
        return ClassifiedError(
            reason=FailoverReason.TIMEOUT,
            should_retry=True,
            recovery=RecoveryAction.RETRY,
            suggestion="Request timed out. Try again."
        )
    elif isinstance(error, InvalidToolError):
        return ClassifiedError(
            reason=FailoverReason.INVALID_TOOL,
            should_retry=False,
            recovery=RecoveryAction.FALLBACK,
            suggestion="Tool not available. Use alternative."
        )
    # ...
```

### 上下文压缩 `agent/context_compressor.py`

```python
class ContextCompressor:
    def compress(self, messages: List[Dict]) -> List[Dict]:
        """压缩策略"""
        # 1. 计算当前 token 数
        current_tokens = estimate_tokens(messages)
        max_tokens = self.max_context_tokens

        if current_tokens < max_tokens * 0.8:
            return messages  # 不需要压缩

        # 2. 保护头部（系统消息 + 前几轮）
        protected_count = self.preserve_head_count
        protected = messages[:protected_count]

        # 3. 压缩中间部分
        middle = messages[protected_count:-protected_count]
        compressed_middle = self._summarize(middle)

        # 4. 保护尾部（最近几轮）
        protected_tail = messages[-protected_count:]

        return protected + [compressed_middle] + protected_tail

    def _summarize(self, messages: List[Dict]) -> Dict:
        """使用 LLM 生成摘要"""
        summary_prompt = f"Summarize this conversation:\n{messages}"
        summary_response = self.llm.call(summary_prompt)
        return {
            "role": "system",
            "content": f"[SUMMARY]\n{summary_response}"
        }
```

---

## 2. Claw-Code (Rust) - 推理循环

### 核心循环 `conversation.rs`

```rust
pub fn run_turn(
    &mut self,
    user_input: impl Into<String>,
    prompter: Option<&mut dyn PermissionPrompter>,
) -> Result<TurnSummary, RuntimeError> {
    let user_input = user_input.into();

    // 1. 记录 turn 开始
    self.record_turn_started(&user_input);
    self.session.push_user_text(user_input)?;

    let mut iterations = 0;
    let mut assistant_messages = Vec::new();
    let mut tool_results = Vec::new();

    // 2. 主循环
    loop {
        iterations += 1;

        // 2.1 检查最大迭代次数
        if iterations > self.max_iterations {
            let error = RuntimeError::new("max iterations exceeded");
            self.record_turn_failed(iterations, &error);
            return Err(error);
        }

        // 2.2 构建 API 请求
        let request = ApiRequest {
            system_prompt: self.system_prompt.clone(),
            messages: self.session.messages.clone(),
        };

        // 2.3 调用 API
        let events = match self.api_client.stream(request) {
            Ok(events) => events,
            Err(error) => {
                self.record_turn_failed(iterations, &error);
                return Err(error);
            }
        };

        // 2.4 解析响应
        let (assistant_message, usage, cache_events) =
            match build_assistant_message(events) {
                Ok(result) => result,
                Err(error) => {
                    self.record_turn_failed(iterations, &error);
                    return Err(error);
                }
            };

        // 2.5 记录使用量
        if let Some(usage) = usage {
            self.usage_tracker.record(usage);
        }

        // 2.6 提取工具调用
        let pending_tool_uses: Vec<_> = assistant_message.blocks
            .iter()
            .filter_map(|block| match block {
                ContentBlock::ToolUse { id, name, input } => {
                    Some((id.clone(), name.clone(), input.clone()))
                }
                _ => None,
            })
            .collect();

        // 2.7 记录迭代
        self.record_assistant_iteration(iterations, &assistant_message, pending_tool_uses.len());

        // 2.8 添加到会话
        self.session.push_message(assistant_message.clone())?;
        assistant_messages.push(assistant_message);

        // 2.9 无工具调用则完成
        if pending_tool_uses.is_empty() {
            break;
        }

        // 3. 工具执行循环
        for (tool_use_id, tool_name, input) in pending_tool_uses {

            // 3.1 Pre-hook
            let pre_hook_result = self.run_pre_tool_use_hook(&tool_name, &input);
            let effective_input = pre_hook_result
                .updated_input()
                .map_or_else(|| input.clone(), ToOwned::to_owned);

            // 3.2 权限检查
            let permission_outcome = if pre_hook_result.is_cancelled() {
                PermissionOutcome::Deny { reason: "hook cancelled".into() }
            } else if let Some(prompter) = prompter {
                self.permission_policy.authorize_with_context(
                    &tool_name,
                    &effective_input,
                    permission_context,
                    Some(prompter),
                )
            } else {
                self.permission_policy.authorize_with_context(
                    &tool_name,
                    &effective_input,
                    permission_context,
                    None,
                )
            };

            // 3.3 执行工具
            let result_message = match permission_outcome {
                PermissionOutcome::Allow => {
                    self.record_tool_started(iterations, &tool_name);

                    let (output, is_error) = match self.tool_executor.execute(
                        &tool_name,
                        &effective_input
                    ) {
                        Ok(output) => (output, false),
                        Err(error) => (error.to_string(), true),
                    };

                    // 3.4 Post-hook
                    let post_hook_result = if is_error {
                        self.run_post_tool_use_failure_hook(&tool_name, &effective_input, &output)
                    } else {
                        self.run_post_tool_use_hook(&tool_name, &effective_input, &output, false)
                    };

                    // 合并 hook 反馈到输出
                    let final_output = merge_hook_feedback(
                        post_hook_result.messages(),
                        output,
                        post_hook_result.is_denied(),
                    );

                    ConversationMessage::tool_result(
                        tool_use_id,
                        tool_name,
                        final_output,
                        is_error
                    )
                }
                PermissionOutcome::Deny { reason } => {
                    ConversationMessage::tool_result(
                        tool_use_id,
                        tool_name,
                        reason,
                        true,
                    )
                }
            };

            // 3.5 记录结果
            self.session.push_message(result_message.clone())?;
            self.record_tool_finished(iterations, &result_message);
            tool_results.push(result_message);
        }
    }

    // 4. 自动压缩
    let auto_compaction = self.maybe_auto_compact();

    // 5. 返回摘要
    Ok(TurnSummary {
        assistant_messages,
        tool_results,
        prompt_cache_events,
        iterations,
        usage: self.usage_tracker.cumulative_usage(),
        auto_compaction,
    })
}
```

### Pre/Post Hook 系统

```rust
// Hook Runner
fn run_pre_tool_use_hook(&mut self, tool_name: &str, input: &str) -> HookRunResult {
    self.hook_runner.run_pre_tool_use_with_context(
        tool_name,
        input,
        Some(&self.hook_abort_signal),
        self.hook_progress_reporter.as_mut(),
    )
}

fn run_post_tool_use_hook(
    &mut self,
    tool_name: &str,
    input: &str,
    output: &str,
    is_error: bool,
) -> HookRunResult {
    self.hook_runner.run_post_tool_use_with_context(
        tool_name,
        input,
        output,
        is_error,
        Some(&self.hook_abort_signal),
        self.hook_progress_reporter.as_mut(),
    )
}
```

### 权限策略

```rust
pub fn authorize_with_context(
    &mut self,
    tool_name: &str,
    effective_input: &str,
    permission_context: &PermissionContext,
    prompter: Option<&mut dyn PermissionPrompter>,
) -> PermissionOutcome {
    // 1. 检查 deny 规则
    if let Some(reason) = self.deny_rules.check(tool_name, effective_input) {
        return PermissionOutcome::Deny { reason };
    }

    // 2. 检查 allow 规则
    if let Some(reason) = self.allow_rules.check(tool_name, effective_input) {
        return PermissionOutcome::Allow { reason };
    }

    // 3. ask 模式 - 需要用户确认
    match self.mode {
        PermissionMode::Prompt => {
            if let Some(prompter) = prompter {
                prompter.decide(&PermissionRequest {
                    tool_name: tool_name.into(),
                    input: effective_input.into(),
                    context: permission_context.clone(),
                })
            } else {
                PermissionOutcome::Deny { reason: "no prompter".into() }
            }
        }
        PermissionMode::DangerFullAccess => {
            PermissionOutcome::Allow { reason: "danger_full_access mode".into() }
        }
        // ...
    }
}
```

### Tracing 事件

```rust
fn record_turn_started(&self, user_input: &str) {
    let Some(tracer) = &self.session_tracer else { return; };
    tracer.record("turn_started", {
        "user_input": user_input.to_string()
    });
}

fn record_assistant_iteration(&self, iteration: usize, ...) {
    let Some(tracer) = &self.session_tracer else { return; };
    tracer.record("assistant_iteration_completed", {
        "iteration": iteration as u64,
        "assistant_blocks": blocks.len() as u64,
        "pending_tool_use_count": pending_tool_uses.len() as u64,
    });
}

fn record_tool_started(&self, iteration: usize, tool_name: &str) {
    let Some(tracer) = &self.session_tracer else { return; };
    tracer.record("tool_execution_started", {
        "iteration": iteration as u64,
        "tool_name": tool_name.to_string(),
    });
}

fn record_tool_finished(&self, iteration: usize, result: &ConversationMessage) {
    let Some(tracer) = &self.session_tracer else { return; };
    // 提取 tool_name 和 is_error
    tracer.record("tool_execution_finished", {
        "iteration": iteration as u64,
        "tool_name": tool_name.clone(),
        "is_error": is_error,
    });
}
```

---

## 3. OpenClaw (TypeScript) - 推理循环

### Agent 命令入口 `agent-command.ts`

```typescript
export async function runAgentAttempt(params: {
  providerOverride: string;
  modelOverride: string;
  body: string;
  resolvedThinkLevel: ThinkLevel;
  sessionId: string;
  // ...
}) {
  const effectivePrompt = resolveFallbackRetryPrompt({
    body: params.body,
    isFallbackRetry: params.isFallbackRetry,
    sessionHasHistory: params.sessionHasHistory,
  });

  // CLI 模式
  if (isCliProvider(params.providerOverride)) {
    return runCliAgent({
      sessionId: params.sessionId,
      prompt: effectivePrompt,
      model: params.modelOverride,
      thinkLevel: params.resolvedThinkLevel,
      timeoutMs: params.timeoutMs,
      // ...
    });
  }

  // 嵌入式模式
  return runEmbeddedPiAgent({
    sessionId: params.sessionId,
    prompt: effectivePrompt,
    model: params.modelOverride,
    thinkLevel: params.resolvedThinkLevel,
    timeoutMs: params.timeoutMs,
    // ...
  });
}
```

### Embedded Agent 执行 `pi-embedded-runner.ts`

```typescript
export async function runEmbeddedPiAgent(params: {
  sessionId: string;
  prompt: string;
  model: string;
  thinkLevel: ThinkLevel;
  // ...
}): Promise<EmbeddedPiRunResult> {
  // 1. 创建会话
  const session = await SessionManager.createSession({
    id: params.sessionId,
    systemPrompt: buildSystemPrompt(params),
  });

  // 2. 发送用户消息
  await session.sendMessage({
    role: "user",
    content: params.prompt,
  });

  // 3. 主循环
  while (true) {
    // 3.1 获取 LLM 响应
    const response = await session.complete();

    // 3.2 检查完成原因
    if (response.stopReason === "stop") {
      return {
        payloads: response.payloads,
        meta: {
          finalAssistantVisibleText: extractVisibleText(response.payloads),
          agentMeta: response.meta,
        },
      };
    }

    // 3.3 处理工具调用
    if (response.stopReason === "tool_use") {
      for (const toolCall of response.toolCalls) {
        // Pre-tool hook
        const preResult = await runPreToolHook(toolCall);

        // 权限检查
        if (!await checkPermission(toolCall)) {
          await session.sendToolResult({
            toolUseId: toolCall.id,
            output: "[PERMISSION DENIED]",
            isError: true,
          });
          continue;
        }

        // 执行工具
        try {
          const output = await executeTool(toolCall);

          // Post-tool hook
          const postResult = await runPostToolHook(toolCall, output);

          await session.sendToolResult({
            toolUseId: toolCall.id,
            output: postResult.modifiedOutput ?? output,
            isError: false,
          });
        } catch (error) {
          // Tool 执行失败
          await session.sendToolResult({
            toolUseId: toolCall.id,
            output: `[TOOL ERROR] ${error.message}`,
            isError: true,
          });

          // Failure hook
          await runToolFailureHook(toolCall, error);
        }
      }

      // 继续循环
      continue;
    }

    // 3.4 其他完成原因（如 max_iterations）
    break;
  }
}
```

### 会话管理 `SessionManager`

```typescript
export class SessionManager {
  async sendMessage(message: Message): Promise<void> {
    this.messages.push(message);
    await this.persist();
  }

  async complete(): Promise<CompletionResult> {
    // 构建请求
    const request = {
      model: this.model,
      messages: this.buildMessages(),
      tools: this.tools,
      systemPrompt: this.systemPrompt,
    };

    // 调用 LLM
    const response = await this.client.complete(request);

    // 解析响应
    const result = this.parseResponse(response);

    // 添加到消息历史
    this.messages.push(result.assistantMessage);

    return result;
  }

  buildMessages(): Message[] {
    return [
      { role: "system", content: this.systemPrompt },
      ...this.messages,
    ];
  }
}
```

### 工具执行

```typescript
async function executeTool(toolCall: ToolCall): Promise<string> {
  const { name, input } = toolCall;

  switch (name) {
    case "bash":
      return await executeBash(input);
    case "read_file":
      return await executeReadFile(input);
    case "write_file":
      return await executeWriteFile(input);
    case "web_search":
      return await executeWebSearch(input);
    case "web_fetch":
      return await executeWebFetch(input);
    // ...
    default:
      throw new ToolNotFoundError(name);
  }
}

async function executeBash(input: BashInput): Promise<string> {
  const { command, timeout } = input;

  // 权限检查
  if (!checkDangerousCommand(command)) {
    throw new DangerousCommandError(command);
  }

  // 执行
  const result = await Bun.spawn({
    cmd: ["bash", "-c", command],
    timeout,
  });

  return result.stdout + result.stderr;
}
```

### 失败恢复 `FailoverError`

```typescript
export class FailoverError extends Error {
  constructor(
    public reason: "rate_limit" | "timeout" | "session_expired" | "api_error",
    public retryable: boolean
  ) {
    super(`Failover reason: ${reason}`);
  }
}

// 使用
try {
  const result = await runAgentAttempt(params);
} catch (error) {
  if (error instanceof FailoverError) {
    if (error.retryable) {
      // 重试
      return retryWithBackoff(params);
    } else {
      // 切换模型
      return fallbackToAnotherModel(params);
    }
  }
  throw error;
}
```

---

# 我们的 Agent vs 三个参考工程 - 详细对比

---

## 代码结构对比

| 组件 | Hermes-Agent | Claw-Code | OpenClaw | **我们的 Agent** |
|------|-------------|-----------|----------|-----------------|
| **入口** | `run_conversation()` | `run_turn()` | `runAgentAttempt()` | `think()` |
| **语言** | Python | Rust | TypeScript | Python |
| **核心循环** | while True | loop {} | while loop | while True |
| **API 调用** | `_call_llm()` | `api_client.stream()` | `session.complete()` | `client.messages.create()` |
| **迭代预算** | `IterationBudget` | `max_iterations` | `timeoutMs` | `max_iterations` |

---

## 核心循环代码对比

### Hermes-Agent (Python)

```python
# run_agent.py ~8417 行
def run_conversation(self, user_message: str, ...) -> Dict[str, Any]:
    # 1. 重置重试计数器
    self._invalid_tool_retries = 0
    self._invalid_json_retries = 0
    self._empty_content_retries = 0

    # 2. 迭代主循环
    iteration_budget = IterationBudget(self.max_iterations)

    while True:
        iterations += 1

        # 3. 检查迭代预算
        if not iteration_budget.consume():
            return "max iterations reached"

        # 4. 自动压缩检查
        if self._should_compress():
            self._compress_context()

        # 5. 构建请求
        request = self._build_api_request(...)

        # 6. 调用 LLM
        response = self._call_llm(request)

        # 7. 解析响应
        assistant_message = response.assistant_message

        # 8. 提取工具调用
        pending_tool_uses = self._extract_tool_uses(assistant_message)

        if not pending_tool_uses:
            return assistant_message.text  # 完成

        # 9. 工具执行循环
        for tool_use in pending_tool_uses:
            pre_result = self._run_pre_tool_hook(tool_use)

            if not self._check_permission(tool_use):
                result = "[PERMISSION DENIED]"
                continue

            try:
                result = self._execute_tool(tool_use)
            except ToolError as e:
                result = f"[TOOL ERROR] {e}"
                self._run_post_tool_failure_hook(tool_use, result)
                continue

            post_result = self._run_post_tool_hook(tool_use, result)
```

### Claw-Code (Rust)

```rust
// conversation.rs ~314 行
pub fn run_turn(&mut self, user_input: impl Into<String>) -> Result<TurnSummary> {
    self.session.push_user_text(user_input)?;
    let mut iterations = 0;

    loop {
        iterations += 1;

        // 检查最大迭代次数
        if iterations > self.max_iterations {
            return Err("max iterations exceeded");
        }

        // 构建请求
        let request = ApiRequest {
            system_prompt: self.system_prompt.clone(),
            messages: self.session.messages.clone(),
        };

        // 调用 API
        let events = self.api_client.stream(request)?;
        let (assistant_message, usage, _) = build_assistant_message(events)?;

        // 提取工具调用
        let pending_tool_uses: Vec<_> = assistant_message.blocks
            .iter()
            .filter_map(|block| match block {
                ContentBlock::ToolUse { id, name, input } => Some((id, name, input)),
                _ => None,
            })
            .collect();

        if pending_tool_uses.is_empty() {
            break; // 完成
        }

        // 工具执行循环
        for (tool_use_id, tool_name, input) in pending_tool_uses {
            // Pre-hook
            let pre_hook_result = self.run_pre_tool_use_hook(&tool_name, &input);

            // 权限检查
            let permission_outcome = self.permission_policy.authorize_with_context(...);

            // 执行工具
            let (output, is_error) = match self.tool_executor.execute(&tool_name, &input) {
                Ok(output) => (output, false),
                Err(error) => (error.to_string(), true),
            };

            // Post-hook
            let post_hook_result = self.run_post_tool_use_hook(&tool_name, &output, is_error);
        }
    }

    // 自动压缩
    self.maybe_auto_compact();
}
```

### 我们的 Agent (Python)

```python
# core/__init__.py ~488 行
async def think(self, prompt: str, status_callback=None) -> str:
    # 1. 获取 bootstrap 组件
    bootstrap = get_bootstrap()
    tracing = bootstrap.get_component("tracing")
    hook_runner = get_hook_runner()
    state_manager = get_state_manager()

    # 2. 初始化状态
    state_manager.update(lambda s: s.set_flag(AgentFlag.RUNNING))

    # 3. Tracing: turn_started
    turn_span = tracing.start_span("agent.turn", ...)

    self.messages.append({"role": "user", "content": prompt})

    while True:
        # 4. 检查 call_depth
        if current_call_depth >= state_manager.state.max_call_depth:
            return "达到最大调用深度"

        # 5. 检查 max_iterations
        if current_iteration >= state_manager.state.max_iterations:
            return "达到最大迭代次数"

        # 6. 自动压缩
        if estimate_tokens(self.messages) > TOKEN_THRESHOLD:
            self.messages[:] = auto_compact(...)

        # 7. 消息预处理
        llm_messages = self._prepare_messages()
        system_msg = {"role": "system", "content": self.get_system_prompt()}
        all_messages = [system_msg] + llm_messages

        # 8. Tracing: llm.call
        llm_span = tracing.start_span("llm.call", ...)

        # 9. 调用 LLM
        response = client.messages.create(
            model=self.config.model,
            messages=all_messages,
            tools=self._tools,
        )

        # 10. Tracing: assistant_iteration_completed
        iteration_span = tracing.start_span("agent.iteration", ...)

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content)  # 完成

        # 11. 工具执行循环
        for block in response.content:
            if block.type == "tool_use":
                # Tracing: tool_execution_started
                tool_span = tracing.start_span(f"tool.{block.name}", ...)

                # Pre-hook
                blocked, modified_input = await hook_runner.run_before_tool_call(...)
                if blocked:
                    return "工具执行被hook阻止"

                # 权限检查
                perm_result = permission_enforcer.check(block.name, block.input)
                if not perm_result.allowed:
                    return "权限被拒绝"

                # 执行工具
                try:
                    output = handler(**block.input)
                except Exception as e:
                    output = f"[{classified.reason.value.upper()}] {e}"

                # Post-hook
                output = await hook_runner.run_after_tool_call(tool_context, output)

                # Tracing: tool_execution_finished
                tool_span.set_attribute("tool_name", block.name)
                tracing.end_span(tool_span)

        # 12. Judge 评估
        if consecutive_tool_calls == 1:
            judge_pass, judge_advice = run_judge(content, user_prompt)

            if judge_pass:
                # 检查是否需要 web_fetch
                if last_tool_name == "web_search" and needs_detail_query:
                    # 注入 web_fetch 提示
                    continue
                self._judge_fail_count = 0
                return content
            else:
                self._judge_fail_count += 1

                # 失败恢复: 2 次失败后触发 ReAct 分析
                should_react, phase = self._failure_recovery.record_failure(...)
                if should_react:
                    analysis = await run_react_analysis(...)
                    recovery_msg = format_recovery_message(analysis)
                    self.messages.append({"role": "user", "content": recovery_msg})
                    continue
```

---

## 功能完整性对比

| 功能 | Hermes-Agent | Claw-Code | OpenClaw | **我们的 Agent** | 状态 |
|------|-------------|-----------|----------|-----------------|------|
| **Pre-Hook** | ✅ | ✅ | ✅ | ✅ | 已实现 |
| **Post-Hook** | ✅ | ✅ | ✅ | ✅ | 已实现 |
| **权限检查** | ✅ approval.py | ✅ PermissionPolicy | ✅ | ✅ PermissionEnforcer | 已实现 |
| **错误分类** | ✅ ErrorClassifier | ✅ Rust Result | ✅ FailoverError | ✅ ErrorClassifier | 已实现 |
| **自动压缩** | ✅ ContextCompressor | ✅ Auto-compaction | ❌ | ✅ microcompact | 已实现 |
| **Tracing** | ✅ | ✅ SessionTracer | ✅ Transcript | ✅ tracing.py | 已实现 |
| **迭代保护** | ✅ IterationBudget | ✅ max_iterations | ✅ timeoutMs | ✅ max_iterations | 已实现 |
| **call_depth** | ❌ | ❌ | ❌ | ✅ | **我们有** |
| **Judge 评估** | ❌ | ❌ | ❌ | ✅ | **我们有** |
| **ReAct 失败恢复** | ❌ | ❌ | ❌ | ✅ | **我们有** |
| **Tool Chain (ISSUE #1)** | ❌ | ❌ | ❌ | ✅ web_search→web_fetch | **我们有** |

---

## 关键差异详解

### 1. 迭代保护机制

**Hermes-Agent**:
```python
iteration_budget = IterationBudget(self.max_iterations)
while True:
    if not iteration_budget.consume():
        return "max iterations reached"
```

**Claw-Code**:
```rust
if iterations > self.max_iterations {
    return Err("max iterations exceeded");
}
```

**我们的 Agent** (多了 call_depth 保护):
```python
# 检查 call_depth (防止无限递归)
if current_call_depth >= state_manager.state.max_call_depth:
    return f"达到最大调用深度 {max_call_depth}，停止执行"

# 检查 max_iterations
if current_iteration >= state_manager.state.max_iterations:
    return f"达到最大迭代次数 {max_iterations}，停止执行"
```

**优势**: `call_depth` 防止工具调用自身的无限递归

---

### 2. Judge + ReAct 失败恢复 (我们独有)

```python
# 工具执行后
judge_pass, judge_advice = run_judge(content, user_prompt)

if judge_pass:
    return content  # 成功
else:
    self._judge_fail_count += 1

    # 2 次失败后触发 ReAct 分析
    should_react, phase = self._failure_recovery.record_failure(...)
    if should_react:
        # 运行 ReAct 分析
        analysis = await run_react_analysis(
            task=user_prompt,
            failure_context=failure_ctx
        )
        # 添加分析结果到消息
        recovery_msg = format_recovery_message(analysis)
        self.messages.append({"role": "user", "content": recovery_msg})
        continue  # 继续执行
```

**对比**: 三个参考工程都没有这个机制

---

### 3. Tool Chain 自动完成 (我们独有)

```python
# 检测 web_search 后是否需要 web_fetch
needs_detail_query = any(kw in user_prompt.lower() for kw in [
    "航班", "天气", "价格", "详情", "时刻表", "股价", "新闻"
])

if last_tool_name == "web_search" and needs_detail_query:
    # 提取 URL 并注入 web_fetch 提示
    url_match = re.search(r'https?://[^\s）\]]+', content)
    if url_match:
        self.messages.append({
            "role": "user",
            "content": f"请使用 web_fetch 工具抓取以下页面获取完整内容：{fetch_url}"
        })
        continue
```

---

### 4. 消息序列化处理 (我们独有)

```python
# 处理 tool_use 响应和 tool_result 消息
for part in msg["content"]:
    if isinstance(part, dict) and part.get("type") == "tool_result":
        tool_content = part.get("content", "")
        tool_id = part.get("tool_use_id", "")
        if tool_id:
            text_parts.append(f"[TOOL_RESULT id={tool_id}]{tool_content}[/TOOL_RESULT]")
```

---

## 三工程对比总结

| 阶段 | Hermes-Agent | Claw-Code | OpenClaw |
|------|-------------|-----------|----------|
| **初始化** | 重置重试计数器 | 创建请求 | 创建 Session |
| **API调用** | `_call_llm()` | `api_client.stream()` | `session.complete()` |
| **响应解析** | `build_assistant_message()` | `build_assistant_message()` | `parseResponse()` |
| **工具提取** | `_extract_tool_uses()` | `filter_map ToolUse` | `response.toolCalls` |
| **Pre-Hook** | `_run_pre_tool_hook()` | `run_pre_tool_use_hook()` | `runPreToolHook()` |
| **权限检查** | `_check_permission()` | `authorize_with_context()` | `checkPermission()` |
| **工具执行** | `_execute_tool()` | `tool_executor.execute()` | `executeTool()` |
| **Post-Hook** | `_run_post_tool_hook()` | `run_post_tool_use_hook()` | `runPostToolHook()` |
| **错误分类** | `classify_api_error()` | Rust Result type | `FailoverError` |
| **结果记录** | `_record_tool_result()` | `session.push_message()` | `session.sendToolResult()` |
| **自动压缩** | `_should_compress()` | `maybe_auto_compact()` | 外部触发 |

---

## 总结

| 方面 | Hermes-Agent | Claw-Code | OpenClaw | **我们的 Agent** |
|------|-------------|-----------|----------|-----------------|
| **代码风格** | Python 面向对象 | Rust Trait 抽象 | TypeScript 模块化 | Python 异步 |
| **核心复杂度** | ~2000 行 run_conversation | ~200 行 run_turn | ~500 行 runAgentAttempt | ~400 行 think |
| **扩展性** | Context Engine 策略模式 | Trait 抽象 | Pi-agent SDK | 模块化导入 |
| **独有特性** | 自改进技能系统 | Rust 性能 + 安全 | 多通道支持 | Judge + ReAct + Tool Chain |

**我们的优势**:
1. ✅ `call_depth` 防止无限递归
2. ✅ Judge 评估机制
3. ✅ ReAct 失败恢复分析
4. ✅ Tool Chain 自动完成 (ISSUE #1)
5. ✅ 错误分类 + 恢复策略

**需要改进**:
1. ❌ 没有 Trajectory 轨迹记录 (Hermes-Agent 有)
2. ❌ 没有模型回退机制 (Hermes-Agent 有)
3. ❌ 会话持久化不完善 (Claw-Code 有)

---

## 参考文件

- Hermes-Agent: `ref/hermes-agent/run_agent.py`
- Claw-Code: `ref/claw-code/rust/crates/runtime/src/conversation.rs`
- OpenClaw: `ref/openclaw/src/agents/command/attempt-execution.ts`
- 我们的 Agent: `agent_framework/core/__init__.py`