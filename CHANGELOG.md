# Changelog

All notable changes to soothe-nano are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.21] - 2026-09-01

### Fixed
- **E402 lint failure in `__init__.py`.** The `bootstrap_dotenv()` call before module imports triggered E402 on all subsequent imports, failing CI. Added `__init__.py` to ruff `per-file-ignores` for E402 and removed redundant inline `# noqa: E402` comments.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.20...v1.2.21

## [1.2.20] - 2026-09-01

### Fixed
- **`.env` loaded at import time.** `soothe_nano` now calls `bootstrap_dotenv()` in `__init__.py` before any `soothe_sdk` import, loading `SOOTHE_HOME/.env` and project-level `.env` files into `os.environ` before YAML config parsing resolves `${VAR}` placeholders. This fixes `fj` (and any other nano consumer) failing on all models in multi-model configs when the shell hasn't exported `DS1_API_KEY` etc. — providers previously resolved with `api_key=None`, causing `AuthenticationError` across the entire failover pool.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.19...v1.2.20

## [1.2.19] - 2026-09-01

### Fixed
- **Silenced litellm's bare-print() debug noise.** `litellm.suppress_debug_info = True` is now set before any LangChain imports, suppressing the "Give Feedback / Get Help" and "LiteLLM.Info" messages that litellm prints to stdout on every exception-mapping call. With `MultiModelChatModel` failover across N instances, each failed model previously produced 2 lines of noise (2*N total), bypassing the logging system entirely. Also added `LiteLLM` to the suppressed third-party loggers in `_suppress_noisy_third_party`.
- **E402 lint violations resolved.** Module-level imports in `provider.py` that must follow the `litellm` import (for the `suppress_debug_info` side-effect) are now annotated with `# noqa: E402`, documenting the intentional ordering. `make lint` passes cleanly.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.18...v1.2.19

## [1.2.18] - 2026-09-01

### Fixed
- **`_model_cache_lock` is now an `RLock` instead of a `Lock`.** `LLMFactory` methods that hold the cache lock call other methods that also try to acquire it, causing a deadlock (`RuntimeError: can't re-enter the same RLock` / frozen thread) under concurrent model creation. Switching to `threading.RLock()` allows re-entrant acquisition within the same thread.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.17...v1.2.18

## [1.2.17] - 2026-09-01

### Added
- **Bypass permissions mode (`interaction_mode="bypass"`).** A new interaction mode that skips all security enforcement layers — policy middleware, operation security (dangerous paths, banned commands), interrupt_on approval prompts, and tool approval pipeline safety checks — giving the agent unrestricted filesystem and shell access within a session. Per-session only (not a config default); selected via the CLI composer mode cycle or per-request via wire field.

### Changed
- **Multi-model router profiles with per-call failover.** The LLM provider now supports configurable router profiles that can fail over across models on a per-call basis.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.16...v1.2.17

## [1.2.16] - 2026-08-30

### Fixed
- **`kill_process` now coerces string PIDs via `args_schema`.** `KillProcessTool` was the only tool in `toolkits/execution.py` without a Pydantic `args_schema`; an LLM-supplied string `pid` (`"14449"` — common when numeric args arrive as JSON strings during streaming) reached `if pid <= 0` and raised `TypeError: '<=' not supported between instances of 'str' and 'int'`, aborting the entire execute step (loop 33c1). Added `KillProcessInput` (`pid: int`) so LangChain coerces before `_run`, plus a defensive `isinstance` guard for direct callers.
- **New `ToolErrorGuardMiddleware` isolates single-tool failures.** Any exception escaping the inner tool-call chain — including the ones the network-error recovery middleware re-raises and everything the graph's default tool-error handler re-raises — is now converted into an `error` `ToolMessage` so the agent self-recovers via the existing `has_tool_error` / deliverable-gate retry loop instead of the whole step dying. Sits outer to `NetworkToolErrorsMiddleware`; `CancelledError` propagates for cooperative shutdown.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.15...v1.2.16

## [1.2.15] - 2026-08-29

### Fixed
- **`_state_retrieval_config` now strips `__pregel_scratchpad`** alongside `checkpoint_ns`/`checkpoint_id`/`checkpoint_map`. The parent Pregel loop's scratchpad carries atomic counters whose `subgraph_counter()` can be > 0 on resume; `AsyncPregelLoop.__init__` then hard-accesses `checkpoint_ns` (already stripped) and raises `KeyError: 'checkpoint_ns'` (loops c982 / 7a90). Mirrors `strip_parent_checkpoint_coordinates` in the host package.

## [1.2.14] - 2026-08-28

### Added
- **`ainvoke_structured_traced` now accepts a `methods` parameter** to override the default structured-output method order (function_calling → None → json_schema → json_mode). Forwarded to `invoke_structured_chat`; when `None`, the default order is used.
- **`decompose_task` timeout default (180s)** added to `ToolTimeoutConfig` defaults, giving the internal grounding-critic LLM call enough time for schema-repair retries.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.13...v1.2.14

## [1.2.13] - 2026-08-27

### Fixed
- **`WorkspaceToolOperationSecurity` now blocks dangerous paths even without a `SecurityConfig`.** Added a bypass-immune `_DANGEROUS_PATH_COMPONENTS` check (`.git/`, `.bashrc`, `.vscode/`, etc.) that runs *before* the `security_config` branch in `_check_filesystem`, so sensitive paths are denied even when no `SecurityConfig` is wired. Mirrors the `DANGEROUS_COMPONENTS` set in `PathValidator`, keeping both layers in sync.
- **Expanded banned command patterns.** `_BANNED_COMMAND_PATTERNS` now also matches `rm -rf` (bare), `rm -r`, `sudo` (bare), `shred`, `chmod 777` (bare), and `git push --force` — bringing coverage in line with soothe's `tool_safety_check.py`.
- **`PathValidator` now flags UNC paths and more dangerous components.** Added `unc_path_forward` (`^//`) and `unc_path_backslash` (`^\\\\`) to `SUSPICIOUS_PATTERNS` (CRITICAL severity). Extended `DANGEROUS_COMPONENTS` with project-config dirs (`.vscode`, `.idea`, `.claude`), shell-config files (`.bashrc`, `.zshrc`, `.profile`, …), and git config files (`.gitconfig`, `.gitmodules`).

### Changed
- **`build_operation_security_request` is now a standalone exported function.** Extracted from `ConfigDrivenPolicy._build_operation_security_request` so external callers (e.g. the soothe tool-approval pipeline, RFC-622 §9b) can build an `OperationSecurityRequest` from a tool name + args without subclassing `ConfigDrivenPolicy`. The method now delegates to the standalone function and preserves the original `action_type`. Exported via `soothe_nano.security.security_api`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.12...v1.2.13

## [1.2.12] - 2026-08-26

### Fixed
- **`lc_to_litellm_messages` drops `tool_calls` with a missing/empty `function.name`.**
  When a resumed long thread carried a historical assistant message whose
  `tool_calls[i]` had `function.name == ""` or no `name` key at all, the
  converter emitted it verbatim and providers rejected the whole request with a
  non-retriable 400 `invalid_request_error`:
  `messages[N].tool_calls[0].function missing required field "name"`. The
  error surfaced in `fjf` (flowjet-agent) as
  `litellm.BadRequestError: OpenAIException`. Extracted
  `_normalize_tool_calls_entry`, shared by both the `BaseMessage` path and the
  dict-passthrough path, which drops malformed `tool_calls` entries (and drops
  the `tool_calls` field entirely when none survive) so a single corrupt
  historical turn no longer fails the entire LLM call.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.11...v1.2.12

## [1.2.10] - 2026-08-24

### Changed
- **`general_purpose_subagent` is now a mode enum.** Replaced the two booleans
  `general_purpose_subagent` (bool) and `general_purpose_subagent_readonly`
  (bool) on `AgentRuntimeConfig` with a single
  `general_purpose_subagent: Literal["off", "full", "readonly", "per_step"]`
  field (default `"full"`). This collapses the prior flag combination into a
  single knob and adds a new `per_step` variant.
  - `off` disables the GP subagent entirely (was `general_purpose_subagent=False`).
  - `full` registers a single GP variant with full filesystem access
    (was `general_purpose_subagent=True, general_purpose_subagent_readonly=False`).
  - `readonly` restricts the GP variant to read-only filesystem tools
    (`ls`, `read_file`, `file_info`, `glob`, `grep`) with write-deny permissions
    (was `general_purpose_subagent=True, general_purpose_subagent_readonly=True`).
  - `per_step` (new) registers two variants — `general-purpose` (full) for
    agent-mode steps (including Eval) and `general-purpose-readonly` for
    plan/ask steps — so a host middleware can redirect `task` calls to the
    read-only variant on plan/ask steps. The model only sees `general-purpose`.
  - `AgentBuilder._compile_deep_agent` now branches on the mode to construct
    the appropriate profile / extra subagent spec; the deprecated
    `general_purpose_subagent_readonly` field has been removed.

### Fixed
- **Per-step GP variant wiring.** The `per_step` mode now constructs a
  `general-purpose-readonly` `SubAgent` spec with a `FilesystemMiddleware`
  restricted to `FILESYSTEM_TOOLS_ASK` and `ask_permissions()`, and appends it
  to the graph subagents so a host middleware can route plan/ask `task` calls
  to it without advertising the variant to the model.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.9...v1.2.10

## [1.2.9] - 2026-08-24

### Added
- **General-purpose readonly subagent.** New `general_purpose_subagent_readonly` config flag
  on `AgentRuntimeConfig` (default `false`). When true and `interaction_mode` is `agent`,
  the general-purpose subagent is configured with read-only filesystem tools
  (`ls`, `read_file`, `file_info`, `glob`, `grep`) and write-deny permissions via
  `GeneralPurposeSubagentProfile`, while the main agent retains full filesystem access.
  Requires `soothe-deepagents>=0.8.6`.
  - `AgentBuilder` constructs a `GeneralPurposeSubagentProfile` with readonly
    tools/permissions/prompt and passes it to `create_deep_agent` via the new
    `general_purpose_subagent_profile` parameter.
  - New `READONLY_GP_SYSTEM_PROMPT` constant in `interaction_mode.py`.

## [1.2.8] - 2026-08-21

### Added
- **New `plan` interaction mode.** A read-only mode that mirrors `ask` constraints
  (read-only filesystem allowlist, write/execute-deny permissions, no mutating tool
  groups, no general-purpose subagent) but is tuned for producing implementation
  plans rather than answering questions. `AgentBuilder` now branches on `plan`:
  applies `FILESYSTEM_TOOLS_PLAN`, `PLAN_POLICY_PROFILE`, `plan_permissions()`,
  an empty `PLAN_SUBAGENT_ALLOWLIST`, and a `PLAN_SYSTEM_PROMPT_SUFFIX` that
  instructs the agent to inspect the workspace with read-only tools and produce a
  clear, actionable plan for approval and execution in Agent mode.
  - `InteractionMode` is now `Literal["agent", "ask", "plan"]`.
  - `resolve_interaction_mode` accepts `"plan"` from the kwarg or
    `agent.runtime.interaction_mode`.
  - `filter_subagents_for_mode` returns an empty list for `plan`.
  - New `PLAN_PROFILE` security profile (read/network/MCP only; no subagent
    spawning) registered in `DEFAULT_PROFILES` as `"plan"`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.7...v1.2.8

## [1.2.7] - 2026-08-21

### Fixed
- **`_StructuredOutputRunnable` tolerates a leaked `CallbackManager` in `config['callbacks']`.**
  When Langfuse is off, a LangGraph node's `AsyncCallbackManager` can leak into
  the structured-output `RunnableConfig`. `_config_for_model` did
  `list(config.get("callbacks"))` to check for the token-usage handler, but a
  `CallbackManager` is not iterable →
  `TypeError: 'AsyncCallbackManager' object is not iterable` →
  `StructuredOutputError` → intake fail-safe routed every query (including
  chitchat like "how are u") as a complex task. Added
  `_flatten_callback_handlers` which reads `.handlers` /
  `.inheritable_handlers` (and recurses through nested lists/tuples) to
  flatten any callback shape to a plain handler list before the membership
  check.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.6...v1.2.7

## [1.2.6] - 2026-08-21

### Added
- **New builtin skills: drawio, office, pdf, anydoc.** Renamed the package
  skills directory `builtin_skills/` -> `builtin/` and updated references in
  `builtins.py`, `index.py`, `README.md`, and tests. Added four new skills:
  - **drawio** — `SKILL.md`, shape index data, references (autolayout,
    derasterize, diagram-types, live-infra, mermaid-authoring, pr-bot,
    shapes, style-extraction/presets, toolbox, troubleshooting, tubemap,
    xml-authoring), ~40 authoring scripts, and built-in style presets.
  - **office** — `SKILL.md`, OOXML (ISO/IEC 29500-4) schema bundles,
    validators for docx/pptx, and scripts for docx/pptx editing, comments,
    recalc, thumbnails, and merge runs.
  - **pdf** — `SKILL.md`, forms/reference docs, and scripts for form
    extraction, filling, bounding-box checks, and PDF-to-image conversion.
  - **anydoc** — `SKILL.md` entry point.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.5...v1.2.6

## [1.2.5] - 2026-08-20

### Fixed
- **Structured-output calls now emit Langfuse generations.**
  `_StructuredOutputRunnable` invoked `ChatLitellmModel._agenerate` directly,
  which skipped LangChain callbacks. Pass 1 / intent, veritas, and other
  `invoke_structured_chat` paths produced a parent span with no child
  GENERATION even when a traced RunnableConfig was passed. The runnable now
  uses public `invoke` / `ainvoke` with `config=`, keeps `response_format` in
  litellm kwargs, and still strips `config`/`callbacks` so handlers are not
  JSON-serialized into the HTTP body. Token usage is recorded via those
  callbacks instead of a second inline `on_llm_end`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.4...v1.2.5

## [1.2.4] - 2026-08-20

### Added
- **Unified Langfuse-traced LLM invocation helpers** (`soothe_nano.llm.traced`).
  Adds `ainvoke_traced`, `ainvoke_structured_traced`, and
  `build_traced_invoke_config` as the single entry point for direct LLM
  `ainvoke` calls. Every call gets Langfuse callbacks (when observability is
  enabled), is wrapped in `await_with_llm_call_policy` for rate-limit/timeout/
  retry, and structured-output calls are traced the same way as plain
  `ainvoke`. The helpers are safe to call without a config (unit tests,
  headless runs) — the call still works, just without tracing.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.3...v1.2.4

## [1.2.3] - 2026-08-17

### Fixed
- **`lc_to_litellm_messages` now accepts plain dict messages.** The planner
  engine (`soothe_nano.subagents.plan.engine`) builds message lists as plain
  `{"role", "content"}` dicts, and LangChain's structured-output runnable
  passes them through to `_agenerate` uncoerced. The converter previously
  raised `AttributeError: 'dict' object has no attribute 'type'` on the
  structured-output draft path. Dict entries are now normalized (role aliases
  like `human`/`ai` mapped to `user`/`assistant`, content coerced to `str`)
  and passed through, preserving any `tool_calls` / `tool_call_id` / `name`
  fields. The `BaseMessage` path is unchanged.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.2...v1.2.3

## [1.2.2] - 2026-08-16

### Fixed
- **`_StructuredOutputRunnable` leaked the LangChain `config` into litellm kwargs.**
  `invoke_structured_chat` passes the LangChain `config` RunnableConfig (with
  `callbacks=[SootheLLMTokenUsageCallbackHandler()]`, injected by
  `merge_token_usage_callbacks`) through `**kwargs`. The runnable forwarded
  every kwarg into `_generate`/`_agenerate` → `_litellm_kwargs` →
  `litellm.completion`, so the live callback-handler object reached the HTTP
  body and failed JSON serialization:
  `litellm.InternalServerError: OpenAIException - Object of type
  SootheLLMTokenUsageCallbackHandler is not JSON serializable`. The structured
  call then raised `StructuredOutputError`, and callers fell back to
  heuristics — every intake `Pass1`/`Pass2` classification degraded to the
  task/simple fallback, so queries routed via heuristic instead of the LLM
  verdict even though the classifiers were initialized in LLM mode. `config`
  is a RunnableConfig, not a litellm kwarg: `invoke`/`ainvoke` now call
  `_split_call_kwargs` to pop it out before forwarding.
- **Token-usage callback now fires inline for structured-output calls.**
  Because the runnable bypasses `BaseChatModel`'s callback machinery, the
  shared handler's `on_llm_end` would no longer run — loop token
  accumulation silently stopped for planner/intent calls. `_fire_token_callback`
  invokes the handler inline, passing the `ChatResult` directly (it
  duck-types as `LLMResult` — do not rebuild an `LLMResult`, pydantic
  revalidation breaks on `ChatResult.generations`).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.1...v1.2.2

## [1.2.1] - 2026-08-16

### Fixed
- **Disable litellm remote model-cost-map fetch.** Set
  `LITELLM_LOCAL_MODEL_COST_MAP=True` before importing litellm so it uses the
  local backup instead of fetching `raw.githubusercontent.com` on every import
  (which timed out and logged a warning when offline).
- **Use `ConfigDict` instead of deprecated `class Config` in
  `ChatLitellmModel`.** Silences the `PydanticDeprecatedSince20` warning
  emitted on every import; class-based config is removed in Pydantic v3.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.0...v1.2.1

## [1.2.0] - 2026-08-16

### Changed
- **LLM utilities refactored into a top-level `soothe_nano.llm` package.**
  Consolidate LLM primitives previously scattered under `utils/llm` into
  `src/soothe_nano/llm` with a single coherent surface: `factory`, `registry`,
  `provider` abstraction, `base` model wrapper, `message`, `tools`,
  `structured` output, `thinking`-token filter, `observability`,
  `invoke_policy`, `response_text`, `schema_wire`, and `types`. The old
  `utils/llm` shims (`factory.py`, `registry.py`, `types.py`, `wrappers.py`)
  are removed; the thin `utils/llm/__init__` re-exports keep existing imports
  working during migration.
- **Provider abstraction is first-class.** `llm/provider.py` (478 lines) and
  `llm/registry.py` (263 lines) formalize provider configs, multi-provider
  factory construction, streaming resolution, and `max_tokens` injection.
- **Structured output re-architecture.** `llm/structured.py` now drives
  `json_schema` method routing with validation-retry recovery from empty
  object payloads — the new-arch equivalent of the legacy wrapper's
  empty-object recovery path.
- **Subagents, middleware, and toolkits** updated to import from the new
  `soothe_nano.llm` package; `diagnose/providers` and `config/settings`
  aligned to the new registry.

### Added
- `examples/llm/` with eight runnable examples (openai, gemini, openrouter,
  anthropic, ollama, dashscope custom endpoint, structured output,
  multi-provider factory) plus a shared `_helpers` module and README.

### Fixed
- `test_role_routing` now constructs a config with role routing disabled,
  matching the middleware's real no-op contract.
- `test_invoke_structured_chat_recovers_from_empty_object_payload` uses a
  `minLength:1` schema so the empty-string first payload fails
  post-validation, exercising the validation-retry path.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.19...v1.2.0

## [1.1.19] - 2026-08-14

### Changed
- **Removed the Muse-Glimmer-specific adapter** (`soothe_nano.utils.llm.muse_glimmer`,
  816 lines) and its test suite (514 lines). The model-agnostic implementation in
  `OpenAICompatModelWrapper` — tool_choice sanitization, `json_schema`
  structured-output routing, thinking-token stripping, and the streaming
  auto-fallback — already covers every OpenAI-compatible provider, so the
  dedicated protocol adapter is no longer needed. New local models sharing the
  wire protocol keep working without a code change.
- **`bind_tools` re-wraps the bound model** in a new `OpenAICompatModelWrapper`
  so thinking-token stripping and the streaming auto-fallback still apply on
  every tool-bound invocation; the previous release shipped this fix but it
  was shadowed in some local installs and is now confirmed green.

### Fixed
- Lockfile markers for platform-conditional dependencies (`zipp` on Python
  <3.12, `cryptography`/`jeepney` on non-Windows) so `uv sync` resolves cleanly
  across platforms.

## [1.1.18] - 2026-08-13

### Changed

- **Protocol detection is now content-based, not name-based.** The
  `muse_glimmer` adapter runs on every generation via
  `OpenAICompatModelWrapper` and no-ops when the wire markers
  (`to=self<|message|>`, `<|eom|>`, `<atem:`) are absent. New models sharing
  the protocol work without a code change or name match.
- **Streaming auto-fallback.** `_stream`/`_astream` now catch LangChain's
  `No generations found in stream` (a server ignoring `stream: true`, e.g.
  vLLM-Metal) and transparently retry via `_generate`/`_agenerate`. Broken
  streaming endpoints self-heal without `streaming: false`.
- **Provider-level `max_tokens`.** `ModelProviderConfig` accepts `max_tokens`;
  `get_provider_kwargs` injects it into `init_chat_model` kwargs so servers
  that truncate when the field is omitted (vLLM-Metal mid-tool-call) set it
  once at the provider level. Caller params still take precedence.
- **`bind_tools` re-wraps the bound model** so the adapter and auto-fallback
  apply on every tool-bound invocation.

### Removed
- `_is_muse_glimmer_model` name-based detection and the `muse_glimmer` flag on
  `OpenAICompatModelWrapper` / `LLMFactory` — superseded by content
  detection.

## [1.1.17] - 2026-08-13

### Added
- **Muse-Glimmer response adapter** (`soothe_nano.utils.llm.muse_glimmer`):
  handles the self-talk wire protocol (`to=self<|message|>…<|eom|>` followed
  by `<|start|>assistant to=user<|message|>…`) emitted as raw `content` by
  vLLM-Metal (`localhost:9543`) and oMLX. Strips self-talk, extracts the
  `to=user` reply, parses six tool-call XML dialects into structured
  `tool_calls` (+ `tool_call_chunks` for streaming), and detects the
  vLLM-Metal chat-template repetition loop.
- Document parsing for Word, PowerPoint, OpenDocument, `.rtf`, and `.epub`
  via `firecrawl-anydoc` (Rust converter, GIL-releasing).
- `ExtractTextTool` advertises and routes the new Office/OpenDocument
  formats.

### Changed
- `LLMFactory` injects a default `max_tokens=2048` for Muse-Glimmer models
  so vLLM doesn't truncate mid-tool-call XML.
- `OpenAICompatModelWrapper` accepts `streaming` and `muse_glimmer` flags;
  when `muse_glimmer` is set, `_generate`/`_agenerate` transform every
  `AIMessage`, and `_stream`/`_astream` buffer the full turn and emit one
  transformed chunk so live reasoning tokens never leak.
- `bind_tools` re-wraps the bound model so the adapter applies on every
  tool-bound invocation; `_extract_tool_param_order` feeds bound tool
  schemas for positional-arg-to-keyword mapping.
- `_parse_document` routes `_ANYDOC_EXTENSIONS` to `_parse_with_anydoc`,
  falling back to PDF/DOCX/TXT.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.16...v1.1.17

## [1.1.16] - 2026-08-13

### Changed
- `LLMFactory` now reads a per-provider `streaming` flag (default `True`) from
  `ModelProviderConfig` and passes `streaming`/`stream_usage` to
  `init_chat_model` accordingly. The model cache key no longer hard-codes
  `streaming:` so providers with the same spec but different streaming settings
  no longer collide.
- `ProviderRegistry.get_provider_streaming` resolves whether LangChain should
  stream a provider's responses; returns `True` for unknown providers.

### Removed
- `soothe_nano.utils.llm.muse_glimmer` adapter and its test suite
  (`tests/unit/utils/llm/test_muse_glimmer_adapter.py`). The adapter worked
  around an oMLX/vLLM-Metal prototype endpoint that ignores `stream: true` and
  returns a single non-SSE JSON body. Instead of translating the model's
  internal self-talk protocol per-model, disable streaming at the provider
  level (`streaming: false`) so LangChain's non-streaming `_agenerate` path is
  used.
- `muse_glimmer` flag and auto-detection (`_is_muse_glimmer_model`) from
  `OpenAICompatModelWrapper` and `LLMFactory`; the `muse_glimmer` exports were
  dropped from `soothe_nano.utils.llm.__init__`.

### Fixed
- `ModelProviderConfig.streaming` field (default `True`) lets a provider opt
  out of streaming for OpenAI-compatible servers whose streaming endpoint is
  broken or unsupported (e.g. vLLM-Metal prototype), avoiding
  `No generations found in stream` errors.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.15...v1.1.16

## [1.1.15] - 2026-08-12

### Added
- Muse-Glimmer response adapter (`soothe_nano.utils.llm.muse_glimmer`): the
  oMLX endpoint model emits a self-talk protocol (`to=self<|message|>…`)
  as raw content and embeds tool calls as XML (``<atem:function_calls>``/
  ``<atem:invoke>``, ``<function name="…"><arg>``, self-named
  ``<read_file file_path="…"/>``) never as structured `tool_calls`. The
  adapter strips self-talk, extracts the `to=user` reply into `content`,
  and parses all six tool-call dialects into structured `tool_calls`
  (+ `tool_call_chunks` for streaming). Streaming turns are buffered and
  emitted as one transformed chunk because the live tokens are internal
  reasoning that must be hidden anyway. Wired into
  `OpenAICompatModelWrapper` via a `muse_glimmer` flag (auto-triggered for
  model names starting with `muse-glimmer`); `bind_tools` re-wraps the
  bound model so the adapter applies on every tool-bound invocation.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.14...v1.1.15

## [1.1.14] - 2026-08-12

### Fixed
- `computer_use` vision loop: attach the latest screenshot as a multimodal
  `image_url` block so the model can see the desktop instead of stalling on
  repeated screenshot-only steps; auto-capture an observation before the first
  step and after each UI action (`action_delay_s`); nudge after consecutive
  observe-only actions; treat screenshot/wait-only runs as no-progress; probe
  and correct Retina `coordinate_scale` from the first full-screen capture.
- `computer_use` input backend: missing `pyautogui` now raises
  `DesktopInputUnavailableError` with install guidance, is logged as
  `input_unavailable` at startup, and is returned as a step-level error rather
  than aborting the whole run (macOS screenshots can still work via
  `screencapture`).
- Stop emitting the noisy `soothe.internal.policy.checked` event on every
  policy check; denials still emit `PolicyDeniedEvent`.

### Changed
- Default `computer_use` `max_steps` raised from 10 to 99.
- Example `07_nano_computer_use_weixin_favorites.py`: bring WeChat forward via
  Spotlight and rely on auto-detected coordinate scale.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.13...v1.1.14

## [1.1.13] - 2026-08-12

### Added
- `computer_use` subagent: `create_computer_use_tools` and
  `resolve_computer_use_backend` factory functions for direct main-agent
  desktop-tool binding (Style 1 — routed delegation), exported from the
  `soothe_nano.subagents.computer_use` package.
- Foreground session tracking for `run_command`: writes
  `{workspace}/.soothe/foreground/fg-{pid}.session` markers while a
  synchronous shell command is in flight so host cancel can reap the
  process group (mirrors the existing `run_background` log tracking).
  New helpers `_register_foreground_session` /
  `_unregister_foreground_session` / `_foreground_session_path` /
  `_resolve_foreground_session_dir` in `toolkits/execution.py`.
- Examples `06_nano_computer_use_example.py` (desktop GUI automation via
  the computer_use subagent) and `07_nano_computer_use_weixin_favorites.py`
  (WeChat Favorites article-link harvester).

### Changed
- `examples/_shared/config.py` injects the repo `src/` dir onto `sys.path`
  so examples run under a foreign venv with a stale flat-snapshot install.
- System prompt: the `computer_use` subagent is advertised in the
  subagent guide and noted as reachable via the `task` tool rather than
  bound directly on the main agent.

### Fixed
- `RunCommandShellTool`: foreground `run_command` invocations now register
  an in-flight session marker so cancellation drains the child process
  group even for synchronous commands; marker is removed on exit.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.12...v1.1.13

## [1.1.12] - 2026-08-11

### Fixed
- `computer_use` subagent: add missing `CallbackManagerForToolRun` import to
  `tools.py` (fixes F821 undefined name at 4 sites) and apply ruff format to
  subagent files and tests (fixes format-check on 6 files). CI verified:
  ruff check passed, ruff format --check clean (444 files), pytest unit
  1596 passed / 42 skipped / 0 failed.
- LLM stack: strip inline thinking tokens (`<think>`, `<thinking>`,
  `<reasoning>`) from DeepSeek-R1-style local model output. Adds
  `thinking_filter.py` with `strip_thinking` (stateless, complete blocks) and
  `ThinkingStreamFilter` (stateful, buffers partial tag fragments split across
  streaming chunks). Stripped content is logged at DEBUG before removal.
- Wire the thinking filter through the LLM stack:
  - `SootheConfig.hide_thinking_tokens` (default `True`; env override
    `SOOTHE_HIDE_THINKING_TOKENS`).
  - `LLMFactory._apply_wrapper_chain` passes the flag to both
    `OpenAICompatModelWrapper` and `SootheTokenUsageChatModel`.
  - `OpenAICompatModelWrapper` strips blocks in `_generate/_agenerate` and
    filters streaming deltas in `_stream/_astream` with per-stream
    `ThinkingStreamFilter` instances.
  - `SootheTokenUsageChatModel` carries the flag for consistent downstream use.
  - `llm_response_text` strips thinking from assembled responses.
  - Export `strip_thinking`/`ThinkingStreamFilter` from the llm package.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.11...v1.1.12

## [1.1.11] - 2026-08-10

### Fixed
- Fallback (no-index) skill scan and `resolve_skill_directory` now label
  `.agents/skills` as `"agents"` and `.soothe/skills` as `"project"`,
  matching the index path. Previously the fallback path used only `"user"`
  for all non-builtin skills, causing inconsistent source labels between
  the fast (indexed) and legacy (full-scan) code paths.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.10...v1.1.11

## [1.1.10] - 2026-08-10

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.9...v1.1.10

## [1.1.9] - 2026-08-10

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.8...v1.1.9

## [1.1.8] - 2026-08-09

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.7...v1.1.8

## [1.1.7] - 2026-08-08

### Changed
- Default `agent.middleware.llm_rate_limit.concurrent_limit` from `8` to `2`
  and `global_concurrent_limit` from `0` to `4` (safer under typical provider
  concurrency quotas; raise for higher-tier APIs).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.6...v1.1.7

## [1.1.6] - 2026-08-08

### Fixed
- `llm_rate_limit_config_from` reads `agent.middleware.llm_rate_limit` instead
  of the removed `agent.loop` path, so direct LLM calls (planner, classifiers,
  autopilot reasoners) honor configured timeouts, retries, and concurrency.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.5...v1.1.6

## [1.1.5] - 2026-08-08

### Added
- `agent.middleware.llm_rate_limit.global_concurrent_limit` (default `0` =
  no global cap), wired to `soothe-deepagents` process-wide LLM concurrency
  slots; per-budget `concurrent_limit` still applies

### Changed
- Require `soothe-deepagents>=0.8.5` for loop-safe LLM rate-limit registry

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.4...v1.1.5

## [1.1.4] - 2026-08-06

### Fixed
- Pin `langchain-mcp-adapters<0.3.1` and `mcp<2.0.0` so standalone CI lock
  resolution stays compatible (mcp 2.0 broke `RequestContext` imports).
- MCP auth transport unit tests import `langchain_mcp_adapters.client` before
  `patch()`.

### Changed
- Web search/crawl (`wizsearch_search` / `wizsearch_crawl`) now call `tarzi>=0.2.3`
  directly. Dropped the `wizsearch` package dependency. Tool names and
  `tools.wizsearch` config keys are unchanged for compatibility. Engines are an
  ordered failover list; crawl uses tarzi WebFetcher (plain HTTP → browser).
- Default `tools.wizsearch.default_engines` is now
  `tavily → google_serper → duckduckgo → bing → brave` (API engines plus
  tarzi's built-in web defaults).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.2...v1.1.4

## [1.1.3] - 2026-08-06

Yanked / not published (CI lock pulled mcp 2.0 incompatibly). See 1.1.4.

## [1.1.2] - 2026-08-04

### Added
- `looprail-creator` builtin skill: authors and validates Soothe LoopRail YAML
  workflow patterns for Autopilot. Covers event/when/then protocol, CE builtins
  only, draft→promote workflow, and protocol-invariant checks. Includes
  `references/looprail-protocol.md` and `references/templates.md`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.1...v1.1.2

## [1.1.1] - 2026-07-31

### Added
- Dual ASK / AGENT interaction modes (opt-in). Default remains AGENT and is
  behavior-compatible for existing callers.
  - `create_nano_agent(..., interaction_mode="ask"|"agent")` and
    `agent.runtime.interaction_mode` config (default `agent`).
  - Hard Ask: read-only `filesystem_tools`, write-deny permissions, `ask`
    policy profile, no `execution`/`file_ops` tool groups, planner-only
    subagent allowlist, Ask system-prompt suffix.
  - Opt-in `DualModeCoreAgent` / `create_dual_mode_nano_agent` with per-thread
    mode pin.

### Removed
- `CodingCoreAgent` compatibility alias; use `SootheNanoAgent`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.0...v1.1.1

## [1.1.0] - 2026-07-31

### Fixed
- `delete` tool no longer crashes with `TypeError: async_delete() missing 1
  required positional argument: 'runtime'`. `SootheFilesystemMiddleware` wrapped
  the tool's `func`/`coroutine` in `*args, **kwargs` closures to supply the
  default `backup_dir`, which erased the `ToolRuntime` annotation that `ToolNode`
  reads to decide what to inject. The default is now supplied only through
  `wrap_tool_call` / `awrap_tool_call`, leaving tool signatures intact.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.15...v1.1.0

## [1.0.15] - 2026-07-31

### Fixed
- Structured chat: bind-time `jsonschema.ValidationError` from
  `JsonSchemaModelWrapper` (e.g. reasoning models returning `{}`) now gets one
  repair-hint retry and method fallback instead of failing the call immediately.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.14...v1.0.15

## [1.0.14] - 2026-07-31

### Changed
- File-operation backups now default to workspace `.soothe/backups` (configured
  in nano) instead of scattered `.backups` folders. `SootheFilesystemMiddleware`
  injects this path when delete omits `backup_dir`; soothe-deepagents remains
  brand-neutral with its own `.backups` default.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.13...v1.0.14

## [1.0.13] - 2026-07-31

### Fixed
- Structured chat: when `function_calling` returns `None` (model emits schema
  JSON in content without a tool call), fall through to `json_schema` /
  `json_mode` instead of retrying the same method. Callers can pass
  `methods=` to prefer JSON response formats on the first request (intake
  classifiers).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.12...v1.0.13

## [1.0.12] - 2026-07-30

### Fixed
- Require `wizsearch>=1.1.9` (pulls `tarzi>=0.1.11`) so blocking web search
  releases the Python GIL. Previously tarzi held the GIL across headless-browser
  I/O and froze the daemon event loop / WebSocket heartbeats during
  `deep_research` / wizsearch fan-out.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.11...v1.0.12

## [1.0.11] - 2026-07-29

### Fixed
- browser_use subagent now stops the browser `Agent.eventbus` from an outer
  `finally` on both happy and failure paths. Previously the bubus `_run_loop`
  re-armed on `CancelledError` and the process hung forever after the answer
  was already printed.
- `operation_guard` denies bare `kill <pid>` against the live daemon, self, or
  parent via protected-kill hooks; banned-command patterns cover common shell
  idioms (port 8765, pidfile, `pgrep soothed`) that resolve the daemon PID.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.10...v1.0.11

## [1.0.10] - 2026-07-29

### Fixed
- `RunBackgroundTool` now declares `RunBackgroundInput` / `args_schema` so LangChain
  strips unknown LLM kwargs (e.g. Cursor-style `description`) instead of raising
  `TypeError: _arun() got an unexpected keyword argument 'description'`.
- Diagnose only fails providers used by the active profile.
- Planner recon tools run via `ToolNode` so `ToolRuntime` injection works.

### Added
- Readonly recon tools for the plan-design subagent.
- Planner stage progress events; nano logs surface in `soothe.log`.

### Changed
- Require `soothe-sdk>=1.0.7`.
- Planner produces a solution report (goal-completion proposal) instead of an
  investigation roadmap.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.8...v1.0.10

## [1.0.8] - 2026-07-25

### Added
- Public `soothe_nano.diagnose` API for package-owned doctor checks (`tool_deps`,
  `providers`, `observability`; deep: MCP, vector stores, models, protocols).
- Tool dependency checks use deepagents `get_rg_bin` / `get_fd_bin` helpers.

### Fixed
- Diagnose status aggregation no longer prefers lexicographic `"ok"` over
  `"error"` when combining `CheckStatus` values (`StrEnum` + `max()`).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.7...v1.0.8

## [1.0.7] - 2026-07-25

### Fixed
- Import `is_rg_available` from `soothe_deepagents.backends.grep_search` (filesystem re-exports were missing in deepagents 0.8.3).
- Omit LangGraph `durability` kwargs when no checkpointer is present (ephemeral execute twin).

### Changed
- Require `soothe-deepagents>=0.8.4` for directory-capable glob (`fd` + scandir) and `grep_search` helpers.
- Workspace/local glob uses deepagents discovery helpers directly; drop the local `grep_search` shim.

### Added
- Directory glob coverage (`trailing /`, `include_dirs`) in unit tests.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.6...v1.0.7

## [1.0.4] - 2026-07-24

### Fixed
- `toolkits.execution` no longer depends on the sunset `langchain-experimental` `ShellTool` / `PythonREPL`; `run_command` and `run_python` are now implemented on `BaseTool` with an in-process REPL. `datetime.utcnow` replaced with timezone-aware UTC.
- Bump `soothe-sdk>=1.0.6` (required for the unified SQLite runtime contract).

### Changed
- Unify SQLite durability, vector store, and persistence under a single process-scoped runtime (`sqlite_runtime`) with a shared runtime lifecycle and pool registry, matching the PostgreSQL control-plane shape.
- Rewrite `sqlite_store` and `sqlite_vec` to route through the runtime, dropping redundant per-instance connection plumbing.
- Centralize SQLite path resolution in `paths.sqlite_paths`, threaded through config models/settings and the resolver infra.
- Align `postgres_pool_lifecycle` / `postgres_pool_registry` with the unified runtime shape.

### Added
- `tests/unit/persistence/test_sqlite_runtime.py` covering the new SQLite runtime.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.3...v1.0.4

## [1.0.3] - 2026-07-24

### Changed
- Drop SDK re-export shims in `events` and `plugin` packages; import the canonical registry and plugin contracts directly from `soothe_sdk`.
- Expose the `project_instructions` prompt module as part of the public API surface.
- Minor refactors in MCP config and the academic / deep research subagent implementations.

### Removed
- Dead code swept across grep search, MCP reconnect, middleware tool-name hints, backend ops, polite HTTP, browser CDP, circuit breaker, outcome preview, prompt clock, and text preview modules.
- Host-owned constants pruned from `events.constants`; nano references only its own protocol type strings.
- Pruned unit tests tied to removed dead code: grep search, static headers provider, prompt clock, text preview, and MCP auth.

### Fixed
- Internal reference numbering aligned to the canonical scheme across tests and module docstrings.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.2...v1.0.3

## [1.0.2] - 2026-07-23

### Fixed
- `ToolOptimizationMiddleware` now redirects simple shell content/path searches (`grep`, `egrep`, `fgrep`, `ag`, literal `rg`, `find -name`) to the native `grep` / `glob` tools, while keeping an escape hatch for true-regex `rg` invocations (metacharacters or explicit regex flags).
- `discovery_hints` module exposes search-backend (`ripgrep` / `python_fallback`) detection helpers.
- Active search backend surfaced in the environment context XML and system-prompt guidance.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.1...v1.0.2

## [1.0.1] - 2026-07-22

### Added
- `WorkspaceAwareBackend.virtual_mode` property and `bind_workspace()` method so deepagents `FilesystemMiddleware` can bind nested task workspaces without host config objects.
- `ToolOptimizationMiddleware`: short-circuit empty `write_todos` payloads and guide on repeated same-path `read_file` slices; expose new metrics counters.
- Tests: workspace-aware backend IG-645 coverage and tool optimization middleware regression tests.

### Changed
- Require `soothe-deepagents>=0.8.2` for workspace bind / GP middleware propagate support.
- `WorkspaceContextMiddleware` resolves `virtual_mode` from the live backend / workspace context instead of injecting `soothe_config`; opts into `propagate_to_general_purpose` so middleware carries into subagents.
- `system_templates`: prefer one wider `read_file` over many offset/limit slices; restrict task subagent to multi-hop reasoning, not mechanical repo search.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.0...v1.0.1

## [1.0.0] - 2026-07-22

### Added
- `ErrorGeneralEvent` registered in the shared `REGISTRY` — canonical `soothe.error.general.failed` model for stream/wire error payloads.
- `mcp-builder` builtin skill for MCP server development, loaded on demand with `skill-creator` instead of at cold start.

### Changed
- Raise `AgentRuntimeConfig.recursion_limit` default from 200 to 9_999 to reduce spurious recursion caps during deep agent runs.
- Decouple nano from the host package: fix import paths from `soothe` to `soothe_nano` in filesystem README, browser-use preview docstring, and toolkits internal docstring.
- Add host extension points in `PostgresPoolRegistry`: template methods `_databases_to_open()` and `_initialize_pool_schema()` let host subclasses prepend checkpoints DB and add schema bootstrap.
- Add injectable pool class params (`metadata_pool_cls`, `checkpointer_pool_cls`) to `resolve_durability`/`resolve_checkpointer` so the host can inject registry-bound subclasses.
- Add `_REGISTRY_CLS` class attribute to `SharedCheckpointerPool` for host subclass override of the backing registry.
- Update resolver and test imports from `soothe.runner.resolver` to `soothe_nano.resolve` (module path migration).
- Point docs and tests at `soothe.coreagent` / `soothe.sloop` instead of the removed `soothe.foundation` namespace.
- Require `soothe-sdk>=1.0.5` for the updated wire constants.

### Removed
- `pytest.importorskip("soothe")` guards from tests; replaced host Veritas schema import with inline schema; dropped Executor tests that depended on host `soothe.sloop`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v0.9.9...v1.0.0

## [0.9.9] - 2026-07-21

### Added
- Extensible builtin skill roots and MCP server catalog — `skill-creator` and `mcp-builder` load on demand; the builtin skill index discovers skill roots without cold-start cost.

## [0.9.8] - 2026-07-21

### Changed
- Share paths via `soothe_sdk` and make the metadata pool extensible — nano no longer hard-codes workspace path resolution; path contracts come from the SDK.

## [0.9.7] - 2026-07-21

### Removed
- Unused / host-owned direct dependencies: `aiosqlite`, `anyio`, `pexpect`, `bubus`, `jinja2`, `openai`, `anthropic`, `pyjwt`, `langgraph-checkpoint-sqlite`, `arxiv`, `tavily-python`, `chardet`, `watchdog` (host already declares checkpointer/JWT/jinja/watchdog; `openai` remains via `langchain-openai`)

### Fixed
- `security.operation_guard` no longer bans remote git operations (e.g. `git push` / `git fetch`); these are gated by the `allow_out` network policy instead. Banned pattern removed; remote git is now permitted for CI and commit workflows.

### Changed
- `events.catalog` no longer redefines `EventRegistry` / `EventMeta` / `EventPriority` / `register_event` locally; it re-exports the canonical implementations from `soothe_sdk.core.registry` and registers protocol events via the shared `register_event`.
- `events.constants` keeps only the protocol type strings nano's own models reference; host-owned MCP/plugin/skill/replay constants removed.
- `plugin.events` corrects type identifiers to `soothe.internal.plugin.*` to match the internal domain classification.
- `skills.events` removes host-owned `SkillActivatedEvent`.
- `resolve._resolver_infra._resolve_sqlite_checkpointer` docstring clarified: it resolves the SQLite checkpointer database path and defers `AsyncSqliteSaver` creation to async context (same pattern as PostgreSQL); callers constructing the saver require `langgraph-checkpoint-sqlite`.

## [0.9.6] - 2026-07-21

### Removed
- `logging.thread_logger.ThreadLogger` (host-owned at `soothe.logging.thread_logger`)
- `config.reload.ConfigWatcher` / `ConfigReloadEvent` / `start_config_watcher` / `stop_config_watcher` / `get_config_watcher` / `DEFAULT_NANO_CONFIG_PATH` / `DEFAULT_CONFIG_PATH` / `ConfigReloadCallback` (host-owned at `soothe.config.reload`)
- `paths.thread_paths.THREADS_DATA_DIR` / `PersistenceDirectoryManager` (host-owned at `soothe.sloop.checkpoints.directory_manager`)
- `workspace.workspace_policy.normalize_user_id` / `user_id_for_hash` / `compute_scoped_workspace_dir_name` / `validate_client_workspace` / `translate_client_path_to_container` / `translate_container_path_to_client` (host-owned at `soothe.workspace.scoped` / `.resolution`)
- `backends.persistence.display_store.DisplayCardStore` / `configure_display_card_store` / `get_display_card_store` (moved to daemon `soothe_daemon.display.display_store`)
- `persistence.sql.soothe_checkpoints.init.sql` (host-owned at `soothe.persistence.sql.soothe_checkpoints`); `cron_jobs` + `identity_*` DDL removed from `soothe_metadata/init.sql` (host applies at runtime)
- `utils.progress.set_step_context` / `reset_step_context` / `get_step_id` (dead — zero callers)
- `utils.error_format.log_exception_simplified` (dead — only its own docstring referenced it)

### Changed
- `persistence.unified.configure_unified_persistence` no longer configures the display-card store (daemon calls `configure_display_card_store` directly)
- `persistence.postgres_pool_registry.open_all` no longer opens a checkpoints pool (host-owned; standalone nano uses `SharedCheckpointerPool` + `AsyncPostgresSaver.setup()`)

## [0.9.5] - 2026-07-21

### Fixed
- Align `WorkspaceAwareBackend` / `NormalizedPathBackend` `edit` with deepagents positional protocol so `edit_file` applies
- Honor `replace_all` through LocalFilesystem → workspace backends (was always forced off)
- Align `grep` / `agrep` with BackendProtocol so middleware `content` mode returns line text; keep `output_mode` keyword-only
- Implement `download_files` / `upload_files` on workspace backends (no longer raise `NotImplementedError`)

## [0.9.4] - 2026-07-21

### Fixed
- Release gate: deepagents dependency floor assertion accepts `>=0.8.x`

## [0.9.3] - 2026-07-21

### Changed
- Adapt workspace filesystem and toolkits to `soothe-deepagents` 0.8.0 (`DeleteResult`, no `ls_info` / backend factories)
- Require `soothe-deepagents>=0.8.0`
- `WorkspaceAwareBackend` no longer implements `__call__` (avoids false factory deprecation warnings)

## [0.9.2] - 2026-07-20

### Added
- Declare `browser-use` as a first-party nano dependency (owned by the browser subagent)

### Removed
- Unused `asyncpg` pin (Postgres paths use `psycopg`)

## [0.9.1] - 2026-07-20

### Added
- Structured LLM invoke retries once with a schema-repair hint when strict JSON Schema validation fails
- Integration test helpers in `tests/conftest.py` for base config loading and API-key gating

### Changed
- Filesystem types and locks come from `soothe-deepagents` directly (no nano protocol re-export shims)
- `LocalFilesystem` write/edit/delete/batch/grep delegate to `FilesystemBackend`
- Skill catalog, index, and builtins discovery use deepagents public skill parse/list APIs
- Require `soothe-deepagents>=0.7.24`

### Removed
- `soothe_nano.filesystem.protocol` and `soothe_nano.filesystem._lock_registry` shim modules
- Parallel `ag`-based grep subprocess stack (search uses deepagents ripgrep + Python fallback)

## [0.9.0] - 2026-07-20

### Added
- Initial public soothe-nano packaging on PyPI as a batteries-included Coding CoreAgent

