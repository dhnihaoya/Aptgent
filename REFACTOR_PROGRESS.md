# Aptgent 重构进度交接文档

> 本次会话只完成了 **Stage 0**（无风险清理），Stage 1–6 待后续会话继续。
> 完整路线图保存在 `~/.cursor/plans/aptgent_refactor_roadmap_5b4e0ed2.plan.md`。
> 用户已确认：明文 API key 暂不动；正确性 Bug（docking cancelled / exit code / wget stderr）单独走 issue，不在本次重构范围。

---

## 1. Stage 0 已完成的修改（13 项）

涉及 21 个文件，净删 142 行，未引入任何回归（同样 6 个失败在 HEAD 上也存在）。

### 1.1 删除死代码

| 文件 | 删除内容 |
|------|---------|
| `aptgent/aptgent/tui/steps/common.py` | `validate_report_summary`（无调用方） |
| `aptgent/aptgent/adapters/rnacomposer.py` | `dataclass_to_dict` + 顶部 `import dataclasses` |
| `aptgent/aptgent/adapters/receptor_prep.py` | `_COORD_RE` 正则 + 顶部 `import re` |
| `aptgent/aptgent/tui/widgets/chat_widgets.py` | `ActivityBubble._FRAMES`（已被 `_breathing_frames` 取代） |
| `aptgent/aptgent/llm/client.py` | `without_thinking` ctx mgr + 顶部 `from contextlib import contextmanager` |
| `aptgent/aptgent/llm/skills/site_proposal/skill.py` | `rephrase` / `rephrase_stream` / `_rephrase_system_prompt` + `load_prompt` import |
| `aptgent/aptgent/llm/skills/site_proposal/schema.py` | `SiteRephraseOutput` |
| `aptgent/aptgent/llm/skills/site_proposal/__init__.py` | `SiteRephraseOutput` 导出 |
| `aptgent/aptgent/llm/skills/__init__.py` | `SiteRephraseOutput` 导出 |
| `aptgent/aptgent/llm/skills/site_proposal/system_rephrase.md` | 整个文件删除 |
| `aptgent/aptgent/workflow/state.py` | `RunState.artifacts` / `RunState.logs` + `ArtifactRef` import |
| `aptgent/aptgent/predictor_runtime/runner.py` | mutation-batch `--output` 参数（未实现） |

### 1.2 删除 unused imports

- `aptgent/aptgent/tui/screens/chat.py` L384：`is_job_done`（仅 import 未用）
- `aptgent/aptgent/jobs/runner.py` L21：`read_last_event`（仅 import 未用）

### 1.3 死分支合并

- `aptgent/aptgent/tui/steps/docking_selection.py` `enter()`：
  - 合并 `editing_form` / `structures_ready` 同分支
  - 删除 `source_selected` phase（全局 grep 确认无任何位置赋值，纯死分支）
- `aptgent/aptgent/workflow/state.py` 中 `DockingRecommendationContext.phase` 注释同步更新

### 1.4 `DockingParamPanel` 去掉未使用构造参

`aptgent/aptgent/tui/widgets/structured_input.py` 中删除：
- `recommended_top_k`
- `receptor_path_note`
- `grid_center_note`

调用方 `docking_selection.py` 中 `DockingParamPanel(...)` 同步去掉这 3 个 kw 实参。

### 1.5 `DockingPlannerSkill.plan` 走 schema 校验

`aptgent/aptgent/llm/skills/docking_planner/skill.py`：
`plan(...)` 改为构造 dict payload 后走 `self.invoke(payload).raw`，让 `DockingPlannerOutput` schema 真正生效。`plan_stream` / `explain_plan_stream` 保持原状（流式无 schema）。

### 1.6 配置卫生

`aptgent/aptgent/config/workflow.toml` 删除死键：
- `[enumeration]`：`max_candidates`、`default_edit_ratio_threshold`、`batch_size`
- `[docking]`：`top_k_strategy`
- 整段 `[llm]`（`default_provider`、`timeout_seconds`、`max_retries` 全部无代码读取）
- 保留 `docking.enabled = false` 并加 `# TODO(Stage 4)` 注释

同步更新：
- `README.md` 中 toml 示例
- `aptgent/tests/tui_helpers.py` 测试 fixture 从 `max_candidates` 改为 `top_k_keep`

### 1.7 配套测试更新

- `aptgent/tests/test_llm_client_payloads.py`：删除 `test_without_thinking_context_disables_thinking`（依赖被删的 `without_thinking`）

---

## 2. 测试现状

跑 `pytest aptgent/tests/` 共 **5 个 + 1 个 deselect**（环境相关）失败，**全部预存在**，与本次重构无关。已在 HEAD 上 stash 验证复现一致。

| 测试 | 失败原因 | 推荐修复方向 |
|------|---------|------------|
| `test_predictor_adapter.py::test_prediction_adapter_uses_internal_runner_module` | 断言 `_build_cmd()` 第一项是字面量 `"python"`，但 conda 下 `sys.executable = /home/dh/.conda/envs/aptgent/bin/python` | 把断言改为 `endswith("python")` 或匹配 `sys.executable` |
| `test_tui_intake_pdb.py::test_intake_retry_full_brief_heuristic_is_conservative_for_pdb_retry` | 调 `handler._looks_like_full_intake(...)` 当方法，但 `intake.py` 用的是 `intake_heuristics.py` 中的自由函数 `looks_like_full_intake`，handler 无此方法 | 测试改为调自由函数，或在 handler 上加 `staticmethod` 兼容引用 |
| `test_tui_intake_pdb.py::test_pdb_input_keeps_sequence_and_requests_missing_target` | 期望 `phase == "awaiting_pdb_selection"`，实际 `"initial"` | 核对 `intake.py` + `pdb_intake.py` 在 b24a038 后 phase 转换链路；要么修代码要么修测试 |
| `test_tui_intake_pdb.py::test_pdb_input_with_multiple_candidates_opens_selection_panel` | 同上，phase 流转预期落空 | 同上 |
| `test_tui_intake_pdb.py::test_mixed_pdb_input_prefers_pdb_sequence_over_user_sequence` | 期望 `current_step` 自动推进到 `SECONDARY_STRUCTURE` 或 `SITE_PROPOSAL`，实际停在 `INTAKE` | 同上 |
| `test_tui_secondary_structure.py::test_secondary_structure_prefers_pdb_derived_result_when_pdb_context_exists` | `StructureHandler._run_rnafold` 无条件调 `rna_fold_adapter.fold(seq)`（`structure.py` L43），不存在"有 PDB context 时从 PDB 派生"分支 | 在 `structure.py` 加分支：若 `pdb_intake.artifact_path` + `selected_chain_id` 都有，调 `PdbAnalysisAdapter.derive_secondary_structure` 派生 dot-bracket，`source="pdb"`，跳过 RNAfold |

**关键结论**：Stage 0 净 0 回归。后续 stage 应保持这个基线，遇到这 6 项失败不要误认为是新引入的。

---

## 3. 还未做的工作（按依赖顺序）

完整内容见 `~/.cursor/plans/aptgent_refactor_roadmap_5b4e0ed2.plan.md`。这里只给摘要。

### Stage 1（in_progress，未提交）— 协议与子进程基础设施抽取

**目标**：消除三处行式 JSON 协议复制 + cancel poller 三份相同实现。

新建子包 `aptgent/aptgent/protocol/`：
- `line_json.py`
  - `class JsonlEmitter(stream)`：`emit(obj)` 内部 `json.dumps(ensure_ascii=False) + "\n" + flush`
  - `def iter_jsonl(reader, on_malformed=None) -> Iterator[dict]`
- `cancel.py`
  - `class StdinCancelWatcher(token="cancel")`：daemon thread 监听 stdin，set `threading.Event`
  - `class CmdFileCancelPoller(cmd_file, cancel_event, interval=2)`：替换 `jobs/runner.py` 三处
- `subprocess_stream.py`
  - `class SubprocessSession(cmd, env, cwd)`：封装 Popen → stdout 行迭代 → stderr drain → cancel(stdin `cancel\n`) → terminate(30s/10s) → kill(5s) 三阶段，对应当前 `adapters/predictor.py` L210–338 `_run_streaming_subprocess`

**改造使用方**：
- `aptgent/aptgent/jobs/events.py` `EventWriter._write` 内部改用 `JsonlEmitter`（保留对外 `write_started/progress/hit/done/error/heartbeat` + `ts` 时间戳语义）
- `aptgent/aptgent/predictor_runtime/runner.py` `cmd_mutation_batch` (L92–185) / `cmd_specificity_batch` (L188–370) 两处 `_stdin_reader` + `_emit` 改用 `StdinCancelWatcher` + `JsonlEmitter`
- `aptgent/aptgent/adapters/predictor.py` `_run_streaming_subprocess` 整体替换为 `SubprocessSession`
- `aptgent/aptgent/jobs/runner.py` 三处 cancel poller（L214–227 enumeration / L484–497 specificity / L750–763 docking）改用 `CmdFileCancelPoller`

**关键保持不变**：
- exit code 约定：rc==0 成功，rc==1 协作 cancel
- terminate→kill 时序：30s wait → terminate → 10s wait → kill → 5s wait
- 出 line 一定走 `flush()`，否则 detached job 看不到实时进度
- `EventWriter` 对外 API 完全不变（`write_*` 方法名和签名）

**验证**：
```
pytest aptgent/tests/test_predictor_adapter_mutation_protocol*.py
pytest aptgent/tests/test_predictor_specificity_batch_protocol.py
pytest aptgent/tests/test_jobs_events.py
pytest aptgent/tests/test_jobs_*runner*.py
```

### Stage 2 — `LLMClient` 四模式统一 + 客户端注入

`aptgent/aptgent/llm/client.py`：
1. 抽内部生成器 `_stream_chat(*, system, user, mode: ChatMode, should_cancel) -> Iterator[StreamEvent]`，统一 4 个 public 方法的 `httpx.stream` + `_iter_sse_events` 框架
2. `_with_retry(self, label, fn)` 统一 `should_cancel + _is_retryable + _raise_after_retries`
3. 抽 `class LLMCallLogger`（`_log_dir`, `_log_call`, `_redact_text`）
4. SSE 解析失败 L277–279 静默 `except: continue` 改为 `_log.debug`
5. `max_reasoning_tokens` → `max_reasoning_chars` 改名 + 旧名向后兼容
6. `chat_stream` 当前用 `response_format=json_object` 但 caller 把 fragment 当 prose 流给 UI，**需确认**是去掉 response_format 还是改名为 `chat_json_stream`

**配置统一**：
- 新增 `LLMClient.from_config(llm_section: dict, *, log_dir: Path | None)` 工厂
- `aptgent/aptgent/bootstrap/container.py` `build_runtime` 创建**共享** `LLMClient`，注入到 `AppRuntime.llm_client`
- `AppRuntime.create_skill(cls)` —— 所有 `SiteProposalSkill()` / `AnalogSuggestionSkill()` / `DockingPlannerSkill()` / `ReportSkill()` 改为 `runtime.create_skill(XxxSkill)`
- 让 `expand_env` 也作用于 `llm.toml` 加载（统一走 `bootstrap/config.load_config`）

### Stage 3 — `workflow/context.py` 模板化

新增 helper：
```python
def patch_context(ctx, updates: dict[str, Any], *, str_keys: Iterable[str] = ()):
    for k, v in updates.items():
        if v is None: continue
        if k in str_keys and isinstance(v, str): v = _clean_text(v)
        setattr(ctx, k, v)
```

改造 7 个 `record_*` 函数（最受益 `record_pdb_intake_context` ~78 行 → ~15 行）。

抽 `aptgent/aptgent/domain/text_utils.py` 统一 `_clean_text` 语义：当前 workflow 层折叠空白、TUI 层只 strip，**两者语义不一致**。改之前要全局检查 PDB title 等含多空格字段是否会被破坏。

### Stage 4 — `sub_batch_size` 透传 + `docking.enabled` 实装

依赖 Stage 1 完成（避免与 protocol 抽取冲突）。

`sub_batch_size` 当前在 `jobs/runner.py:128` 被读取但 **从未传给 adapter / CLI**：
- `aptgent/aptgent/adapters/predictor.py` `predict_mutation_batch` 增加 `sub_batch_size: int | None = None` 参数，透传到 CLI `--sub-batch-size {n}`
- `aptgent/aptgent/predictor_runtime/runner.py` `cmd_mutation_batch` 接收并传给 predictor
- `aptgent/aptgent/jobs/runner.py` 读取后传入 adapter 调用
- 把误导性的 `batch_size` 参数名（实际只控制 `progress_every`）拆开

`docking.enabled = false` 实装：在 `aptgent/aptgent/tui/steps/docking_selection.py` `enter()` 或 `workflow/engine.py` 读取 `workflow_config["docking"]["enabled"]`，若 false 则跳过 docking_selection + docking_run 直接到 spatial_rank（需要补一条 transition 边到 `TRANSITIONS`）。

### Stage 5 — `docking_selection.py` 最小改动

- 抽 `_apply_docking_plan(state, *, receptor_paths, grid_boxes, source, top_k)`：去掉 L487–499 与 L629–641 的重复块
- `_candidate_id(cand, i)` helper（4 处重复）
- `_top_k_bundle(state) -> tuple[int, list[Candidate]]`（3 处重复）

### Stage 6 — `common.py` 按 domain 拆分（最后做）

依赖 Stage 2（`run_llm_interaction` 可能涉及）、Stage 3（text_utils 就位）。

目标结构：
```
aptgent/tui/steps/common/
  __init__.py              # re-export 公共 API
  coercion.py
  llm_ui.py                # run_llm_interaction
  intake_format.py
  site_proposal_validate.py
  specificity_format.py
  docking_plan.py
```

迁移分 3 步：新建 + re-export → 逐 step 改 import → `common.py` 收为薄壳。

---

## 4. 注意事项

1. **路线图位置**：`~/.cursor/plans/aptgent_refactor_roadmap_5b4e0ed2.plan.md`（不要在新对话改这个文件，已包含完整规划）。
2. **明文 API key**：`llm.toml` 中的 `sk-...` 用户要求保留不动。
3. **正确性 Bug 不要在重构中夹带**：docking 误标 cancelled、`write_error` 后 exit 0、wget TimeoutExpired.stderr 这些另开 issue。
4. **测试基线**：HEAD 已有 6 个失败（见上表），Stage 1+ 跑测试时把这 6 个视为已知 baseline，新增的失败才是回归。
5. **未提交**：Stage 0 的所有改动都还在 working tree，未 commit。如果你想保留这次清理，需要单独 `git add` + `git commit`。

---

## 5. 当前 working tree 状态

```
README.md                                          |  4 +--
aptgent/aptgent/adapters/receptor_prep.py          | 10 --------
aptgent/aptgent/adapters/rnacomposer.py            |  6 -----
aptgent/aptgent/config/workflow.toml               | 10 +-------
aptgent/aptgent/jobs/runner.py                     |  2 +-
aptgent/aptgent/llm/client.py                      | 10 --------
aptgent/aptgent/llm/skills/__init__.py             |  2 --
aptgent/aptgent/llm/skills/docking_planner/skill.py| 22 ++++++++--------
aptgent/aptgent/llm/skills/site_proposal/__init__.py| 2 --
aptgent/aptgent/llm/skills/site_proposal/schema.py |  7 -----
aptgent/aptgent/llm/skills/site_proposal/skill.py  | 24 +----------------
aptgent/aptgent/llm/skills/site_proposal/system_rephrase.md | 5 ---- (deleted)
aptgent/aptgent/predictor_runtime/runner.py        |  1 -
aptgent/aptgent/tui/screens/chat.py                |  2 +-
aptgent/aptgent/tui/steps/common.py                | 12 ---------
aptgent/aptgent/tui/steps/docking_selection.py     |  9 +------
aptgent/aptgent/tui/widgets/chat_widgets.py        |  9 -------
aptgent/aptgent/tui/widgets/structured_input.py    |  6 -----
aptgent/aptgent/workflow/state.py                  |  9 ++-----
aptgent/tests/test_llm_client_payloads.py          | 30 ----------------------
aptgent/tests/tui_helpers.py                       |  2 +-
21 files changed, 21 insertions(+), 163 deletions(-)
```

新对话开始时建议先：
```bash
cd /home/dh/Aptgent
git status                                    # 确认 working tree
git diff --stat                               # 看看 Stage 0 改动
git add -A && git commit -m "..."             # 如果要保留 Stage 0
# 然后从 Stage 1 继续
```
