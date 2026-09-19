- Proposal Name: `memory_quality_and_lifecycle`
- Start Date: 2026-09-18
- Status: Proposed
- RFC PR: [oceanbase/powercontext#1652](https://github.com/oceanbase/powercontext/pull/1652)
- Tracking Issue: [oceanbase/powercontext#1590](https://github.com/oceanbase/powercontext/issues/1590)
- Related RFCs: [RFC 0014](0014_memory_layer_design.md)、[RFC 0019](0019_local_source_memory_runtime.md)、
  [RFC 0028](0028_context_pack.md)、[RFC 0050](0050_artifact_candidate_review_inbox.md)、
  [RFC 0080](0080_memory_search_reranking.md)、[RFC 1229](1229_unified_workloads_and_long_horizon_memory_evaluation.md)、
  [RFC 1557](1557_recurring_failure_repair.md) 和 [RFC 1560](1560_recall_sufficiency_gate.md)
- Related work: [#1425](https://github.com/oceanbase/powercontext/issues/1425)、
  [#1321](https://github.com/oceanbase/powercontext/issues/1321) 和
  [#1556](https://github.com/oceanbase/powercontext/issues/1556)

# 摘要

本 RFC 定义一套可选、保留 evidence 的 Memory 质量与生命周期策略。它引入四个相互独立的派生维度：
provenance/verification、importance、novelty 和 current-state status，用于维护健康的活跃 Memory 检索面，
同时不改变权威 entry 正文、Artifact Revision、citation 或公开 RRF score。

首阶段策略刻意保持保守：先过滤生命周期已明确失效的记录，再在固定 RRF 粗排池内部做最大 `±2` 位的稳定调整。
它既不改变 channel admission，也不会把池外 entry 带入 reranker。近重复检测只生成关系与 review proposal，
不会自动执行破坏性合并。后续 L1 策略可以在默认关闭、dry-run 优先的前提下可恢复地停用低价值 entry；
风险更高的 consolidation、supersession 和 promotion 属于受 review gate 约束的 L2 扩展。

本设计明确区分“可恢复的停用”和“自动操作副作用的回滚”，并把逻辑生命周期与物理删除、合规保留及跨 family
清理分开；后者继续由 #1425 和后续 RFC 负责。

# 动机

Memory 已提供不可变 entry version、manifest state、精确 citation、FTS/vector admission、RRF fusion 和可选的
listwise reranking，但当前活跃检索面仍存在三个缺口：

1. 有 evidence 支持的长期 constraint 与一次性的弱 working note 没有显式质量差异。
2. 现有精确内容检查无法控制同一 instruction 或演进事实的多个活跃改写版本。
3. 已知 inactive 或 superseded 的记录缺少可供检索链路使用、且独立于 relevance/reranker 的时间有效性标注。

这三类问题不能混为一谈。质量不是写入准入策略，语义相似也不能证明两条记录可以合并，生命周期有效性更不是
软排序偏好。混用这些概念会让低质量 entry 从历史中消失、让 reranker 看见已撤销 evidence，或让简单的新近性
压过长期有效的 constraint。

目标策略如下：

```text
直接写入 grounded Memory
  -> 保留不可变 entry authority 与 evidence
  -> 派生有界 lifecycle/quality projection
  -> 在检索排序前执行已知 validity
  -> 只重排固定 RRF pool
  -> 仅可恢复地停用明确符合条件的低价值 entry
  -> consolidation、supersession、promotion 必须 review
```

# 指南级说明

## 普通 Memory 写入保持不变

本 RFC 不要求普通 `remember` 调用等待 Review。例如“修改文档后运行 `make docs-test`”仍是普通 Memory 写入，
并保留其精确 evidence 与不可变 entry version。

所有生命周期选项关闭时，当前 write、search、rerank、Context Pack 和 citation 行为保持不变。新策略不允许
改写 entry 正文、静默删除历史或改变公开 Memory search score。

## 当前状态检索与历史检索不同

假设项目最初记录：

```text
文档修改必须运行 make test。
```

后来直接 evidence 确立：

```text
文档修改必须运行 make docs-test。
```

经 review 并记录显式 supersession relation 后，普通 current-state recall 只返回后一条。旧记录不是简单降权，
而是在 RRF 和可选 reranking 之前被过滤；精确历史读取仍可解析旧 entry 及其 supersession reason。

如果两条记录只是看起来矛盾，而 PowerContext 缺少可靠关系 evidence 或可比较时间，则必须保留两者并标为
`unresolved_conflict`。Context Pack 应显式标注未解决 evidence，不能要求 Agent 根据正文或 rank 猜测先后关系。

## 质量只影响已检索到的 evidence

一次搜索先执行常规 channel retrieval、admission、lifecycle-validity filtering、RRF 和 coarse-pool truncation，
之后质量策略才可在相同成员集合内做很小的稳定调整：

```text
baseline RRF members:   A  B  C  D  E  F
quality-adjusted order: A  C  B  D  E  F
```

不会出现新成员。没有通过 RRF 截断的 entry 不能被质量策略提升进 reranker 输入。这使质量保持为保守选择辅助，
而不是隐藏的第二套 recall 机制。

启用 RFC 1560 recall gate 时，其 sufficiency assessment 和 budget probe 使用 baseline order。只有 gate 停止发起
新 round 后才应用质量重排，因此质量不会改变扩展决策或成本核算。

公开 hit 的 `score` 始终是 baseline RRF score。新的进程内 `MemoryRankingTrace` 用于解释有界重排；首阶段不把
该 trace 加入 HTTP search 输出。

## Forgetting 是退出活跃面，不是擦除历史

可选 L1 maintenance job 可以找出低 importance、已过期且未受保护的 entry。它必须先以 dry-run 运行；启用写入后，
通过普通 Memory deactivate Revision 记录稳定 reason，例如 `auto_decay:v1`。

entry 正文、旧 Revision、evidence 与精确 citation 都继续存在。`reactivate()` 把同一 entry version 恢复到活跃
projection，并开始新的生命周期区间。这叫“可恢复停用”，不承诺撤销该 entry 已造成的所有下游副作用。

## 语义维护必须经过 Review

两条改写 entry 可能需要 alignment，反复出现的 working note 也可能值得 promotion，但这些都不是自动 mutation。
L2 task 创建包含精确受影响版本、evidence、proposed relation 和所有预期效果的 proposal；只有 approval 才能产生
Memory Revision 或改变 lifecycle relation。

普通 Memory 继续直接写入。L2 是 RFC 0050 review mechanism 的受限 Memory 扩展，不会让所有 Memory 写入进入 Review。

# 参考级说明

## 设计不变量

1. **不可变 authority。** Entry body、entry content hash、Artifact Revision、evidence citation 和精确 Handoff
   citation identity 保持权威且不可变。
2. **默认不回归。** 所有 lifecycle option 默认关闭或中性；旧数据使用中性派生值。无法完成可靠派生时关闭功能，
   不能猜测。
3. **Validity 先于 quality。** 对普通 current-state recall，已知 `inactive` 和显式 `superseded` 记录在 RRF 与
   reranker 之前过滤，且不依赖 quality、freshness 或模型可用性。
4. **Quality 不是 admission。** Importance、novelty、provenance 和 current-state metadata 不决定 entry 能否写入
   或通过 lexical/vector admission，只影响有界排序或维护资格。
5. **不确定时间安全失败。** 缺少可靠 relation 或时间未知/不可比时保留 `unresolved_conflict`；不能把 relevance
   或 RRF order 当作时间 evidence。
6. **精确定义 reversibility。** L1 只承诺可恢复停用；L2 必须记录 operation 并定义 compensation，
   `reactivate()` 本身不是 consolidation、promotion 或 derived view 的完整 rollback。
7. **后端一致。** SQLite 与 OceanBase 必须具有相同的 validity filtering、bounded ordering、lifecycle reason、
   rebuild 和 disabled-mode 结果。

## 权威状态与派生状态

现有 Memory manifest 继续作为 active/inactive state 的 authority。本 RFC 增加一个可重建的 Memory lifecycle
projection，与现有 current-head search projection 相邻，使用精确 Memory artifact、entry 和 entry-version identity
作为 key；它可以扩展 head storage，也可以使用独立 projection table。

该 projection 不包含替代正文，其逻辑结构为：

```text
entry identity: memory_artifact_id, entry_id, entry_version_id
quality:        importance, evidence_strength, provenance class, novelty relation summary
validity:       current | inactive | superseded | unresolved_conflict
lineage:        validity_reason, successor identity when known
time:           recorded_at/effective_at plus an explicit unknown state
lifecycle:      tier, protected/pinned state, lifecycle interval, automatic-action reason
observability:  bounded source/artifact reference counts and rule-version identifiers
```

projection 从权威 Memory Revision、精确 evidence reference、声明式 Source attribute 和有界 lifecycle/operation
record 派生，必须能完整重建，不能影响 entry content hash 或成为第二份正文 authority。

时间值必须有显式持久化规则。`recorded_at` 由首次观察 entry 的 lifecycle/write operation 写入；只有 evidence
明确提供时间时才接受 `effective_at`。Operation record 绑定精确 Memory revision 和 entry-version identity，
使 rebuild 不依赖当前 wall clock 或后端 row timestamp。缺少记录的旧 entry 保持 `unknown`，freshness 中性，且在
后续权威事件提供可用时间前不能参加基于 age 的 L1 deactivation。单独的派生 `created_at`/`revised_at` 不足以让
旧 entry 获得自动过期资格。

`MemoryHit` 继续只携带现有 identity、text、公开 RRF score 和 matched channels。Read path 可以附加内部
`MemoryContextAnnotation`，包含 validity、reason/successor、time-known state 和有界 provenance summary；
Context rendering 使用它标注 current、historical 或 unresolved evidence。

## Source authority 与 verification 前置条件

当前 `Source` 只有 `name`、`definition_version`、`materialization` 和 `description`；`SourceDefinition` 只有 version
与 projection。二者都没有 authority/verification declaration，`SourceRef` 也只是 identity，不能用于猜测 trust。

启用 stage-1 quality ranking 前，Source registration 必须增加一个可重建的 adapter contract，暂命名为
`MemoryEvidenceDeclaration`：

```text
SourceDefinition.memory_evidence:
  authority: untrusted | user_asserted | repository_attested | system_attested
  verification: unknown | verified | not_verified
  declaration_version: stable contract version
```

具体枚举名可以在实现 Source contract 时调整，但必须满足：

- 由 adapter 或受信 registration configuration 显式声明；
- declaration 有版本且能为历史 Source materialization 重建；
- 正文、`SourceRef` 或模型不能伪造更强 declaration；
- 缺失 declaration 解析为 `unknown`/untrusted，不能启用 stage-1 quality ranking。

写入 Memory entry 时，需要把 declaration version 和已解析 authority/verification 快照到该精确 Source
materialization 的有界 lifecycle evidence。重建使用当时有效的历史 declaration，而不是当前 registry 结果。
快照缺失或不可验证时，entry 保持 `unknown`/untrusted，ranking policy 对该 deployment 保持关闭。

这是 Source/SourceDefinition adapter surface 的前置变更，必须在 ranking feature 之前落地。首个 ranking policy
不使用 `verified_source_bonus` 或模型生成的 authority score。

## 相互独立的质量维度

| 维度 | 派生来源 | Stage-1 用途 | 禁止的捷径 |
| --- | --- | --- | --- |
| Provenance/verification | 声明式 Source contract 与精确 evidence | 保护 authority-sensitive record；校准后可提供有界正向排序信号 | 从 `SourceRef`、正文或模型推断 |
| Importance | 确定性的 entry-version feature | 有界排序与 L1 eligibility | 模型自由评分 |
| Novelty | normalized equality 与有界 relation check | relation/proposal 与 density observability | 自动降低 importance 或语义删除 |
| Current-state | 显式 entry classification 与 temporal query intent | 仅决定 freshness eligibility | 通用“越新越好” |

Stage 1 不产生 `importance_band`、`importance_reason` 或模型 ranking bonus。确定性 importance 初始规则为：

```text
base(kind):       fact=1, preference=1, decision=2, constraint=2, working_note=0, unknown=1
updates_state:    evidence-backed revise 改变 current state 时 +1
thin_penalty:     stage 1 固定为 0；未来仅在校准后用版本化确定性规则引入 -1

importance = clamp(base + updates_state - thin_penalty, 0..3)

caps: weak evidence、session tier 与未经佐证的 working note 不得高于 normal。
```

这些都是校准 seed，而不是默认启用值。Score 在 add 或 evidence-backed revise 时重算，不通过周期性模型重新评级。
未知 kind 使用中性 normal base。Stage 1 不从文本推断 thin penalty；未来 content-density rule 必须确定、版本化，
且缺少输入时关闭。Score 可以通过显式 revise、corroborating evidence 或用户 override 改变；validity 和 novelty
不能从 importance 推断。

## Validity 与时间行为

普通 current-state recall 在 channel admission 之后、RRF 之前执行：

| Projected validity | 普通 current-state recall | 精确/历史读取 |
| --- | --- | --- |
| `current` | eligible | eligible |
| `inactive` | filtered | 携带 deactivation reason 可用 |
| `superseded` | filtered | 携带 successor/reason 可用 |
| `unresolved_conflict` | eligible 且带标注 | eligible 且带标注 |

首阶段不增加通用 HTTP historical-search 参数。现有精确 Artifact 与 entry-version resolution 继续作为历史路径。
未来 public temporal query API 必须显式指定 requested view，不能把历史问题静默按普通 current-state search 处理。

推断出的 semantic relation 不足以设置 `superseded`；必须经过 L2 approval 或具有直接权威 lifecycle evidence。
未知或不可比较时间保持显式 `unknown`，永远不能作为排序 key。

## 检索算法与固定成员集合

对 query `q`、请求 limit `k` 和当前 search configuration，stage 1 为：

```text
per-channel candidates
  -> existing FTS/vector admission
  -> validity filtering for requested temporal view
  -> baseline RRF and coarse-pool truncation
  -> [recall gate enabled] baseline-only sufficiency assessment and bounded expansion
  -> final baseline fixed pool
  -> bounded stable quality reorder inside final pool
  -> optional listwise reranker over same member identities
  -> final limit
  -> existing Context Pack candidate and byte budgets
```

当前 `fuse_rankings()` 在自身 `limit` 内截断；`MemoryService` 传入 `coarse_limit`，无 reranker 时等于 `k`，
有 reranker 时至少等于配置的 reranker candidate limit。Quality 只能在截断后运行，不能扩展 fusion、降低
admission threshold 或改变 reranker member identity。

recall gate 关闭时，final baseline pool 就是单轮 post-RRF pool。启用时，gate 只使用 baseline order 和 baseline
Builder-fit result；quality reorder 与 listwise reranking 不参与 gate decision。Gate 停止扩展后形成最终固定 pool，
再执行确定性的 `bounded_stable_reorder`：

1. 从固定 RRF sequence 开始。
2. 根据独立维度和 query intent 计算带 policy version 的 proposed rank adjustment。
3. 生成稳定顺序，每个成员相对 baseline 最多移动两位，tie 保留 baseline RRF order。
4. 断言 before/after identity set 完全一致。

旧的 `0.5..2.0` 乘法方案被拒绝。RRF constant 为 60 时，单 channel rank-1/rank-10 比约 1.15，rank-1/rank-30
约 1.48，rank-1/rank-64 约 2.03；4 倍 multiplier 会成为主导排序项，而不是有界 tiebreaker。

Freshness 是独立 query-time hint：

```text
freshness(age) = alpha + (1 - alpha) * 2^(-age / half_life)
```

`alpha` 与 `half_life` 只是校准输入。只有显式 current-state record 和显式 current/temporal query intent 才能使用；
historical fact、completed decision 及 unknown time 都保持中性。Freshness 不与 importance 相乘，也不能降低
high-authority 或 critical record。首阶段 revision age 只是 proxy，不是 usage-frequency memory。

## Ranking trace

`MemoryRankingTrace` 是新的进程内诊断值，与 RFC 0080 的 `MemoryRerankTrace` 分离；本 RFC 提出时 `master`
尚无该类型。它只记录有界、无正文的 decision data：

```text
policy identifier and parameter version
baseline fixed-pool identities and baseline ranks
quality-adjusted order and bounded displacement
dimension/rule codes used for each adjustment
validity-filter count and unresolved-conflict count
membership_changed = false
```

无论是否启用 reranking 都可产生该 trace。它不改变公开 RRF `score`、不增加 HTTP field，也不复用只有启用
reranker 才存在的 rerank trace。

## 与 recall sufficiency（RFC 1560）的兼容性

[RFC 1560](1560_recall_sufficiency_gate.md) 的默认关闭 recall gate 可以用放宽后的 `AdmissionFloor` 发起额外有界
搜索。该 expansion 是新的 recall round，不是 quality 驱动的 pool-membership change。

每轮都在 channel admission 后、baseline RRF 前执行 validity filtering。Gate 累积并评估 baseline-order candidates，
Builder budget probe 也使用 baseline order。Quality reorder 与可选 listwise reranker 只在 gate 结束后作用于最终固定
pool。因此 quality 不得改变是否扩展、最大或实际 round 数、admission floor、query-embedding reuse、admission/cost
accounting 或进程内 `RecallEffort` sink。`MemoryRankingTrace` 与 gate aggregate effort trace 保持分离。评测必须
确认最终 quality reorder 保留最终 reranker member identities，且每轮 gate 都遵循 RFC 1560 baseline view。

## 近重复 alignment

近重复 alignment 是有界 write-side candidate procedure，不是破坏性 deduper。权威 `entry_content_hash` 不是
text-only hash；它覆盖 canonical kind、text、Source references 与 Artifact references。可以增加独立派生的
text fingerprint 查找 normalized textual equality，但它不能替代权威 hash，也不能授权丢弃新的 evidence refs：

```text
normalized text fingerprint
  -> bounded lexical candidates
  -> optional top-k semantic neighbors within target Memory
  -> relation/evidence-increment record or review proposal
```

权威内容完全匹配时保留现有 no-op 行为。若 text fingerprint 相同但 evidence 不同，则生成 evidence-increment
relation 或 review proposal，而不是 no-op。`tau_same`、`tau_similar` 等 semantic threshold 都只是校准输入。
Semantic relation 不能自动把 importance 降为 `low`、deactivate entry、merge body 或设置 `superseded`。

无 embedding deployment 可以收集确定性 lexical evidence 并生成 review proposal，但不能自动合并或丢弃改写记录。
直接 explicit write 和 deterministic adapter 可保留已有 idempotency path；bulk import 可把有界检查延后至 offline
health pass。

## Recall feedback

普通搜索保持只读。Stage 1 不加锁、不持久化 recall event，也不更新 `last_recalled_at`；首个 policy 只把 revision
age 作为有限 activity proxy。

未来可选能力可以异步记录有界 recall event 并折叠进 projection。ACT-R base-level learning 只为该后续能力提供
理论动机：它是多个 practice timestamp 的 power-law sum，而不是本 RFC 的单一 revision-age proxy。Frequency 必须
与 provenance protection 一起引入，避免低 authority entry 仅因频繁访问而获得影响力。

## L1：可恢复的自动停用

L1 默认关闭并必须支持 dry-run。只有同时满足以下条件才能 deactivate entry：

1. 权威 manifest 与 lifecycle projection 都判定其 active/current；
2. importance 不高于配置 floor，初始只允许 `low`；
3. 适用 retention interval 已到期；
4. entry 未 pinned、protected 或被用户显式 retired；
5. 它不是等待显式 session/task boundary 的 session-tier entry；
6. 不存在会破坏 evidence lineage 的未解决 inbound relation 或未处理 derived view。

L1 调用 `forget(..., reason="auto_decay:v1")` 并记录有界 action reason。它必须幂等，并使用正常 scope-lock/head-CAS。
`reactivate()` 恢复原 entry version，不创建新 body version。用户操作优先：显式 restore 开始新的 lifecycle interval，
用户 revise 刷新派生时间与质量。

`session_end` 是独立的确定性 lifecycle event，不是 age/importance L1 decision。Caller 结束 session/task 时，
`session` tier entry 可以用 `reason="session_end"` 停用，无需等待 retention/importance threshold，但仍需通过保护与
并发检查，并保持可恢复。L1 age path 不处理 session tier，避免 tier 规则与 low-importance floor 冲突。

| Tier | 用途 | Lifecycle behavior |
| --- | --- | --- |
| `session` | caller 标记的 task/session note | 在显式 boundary 以 `session_end` 停用；可恢复 |
| `short` | 临时 working note | 使用更短的配置 retention window |
| `long` | 长期 constraint、decision 或 historical fact | 使用普通 protection 与 retention path |

Capacity pressure 只创建有界 cleanup proposal，不自动 compact。“每 50 个新 low entry”或“inactive 超过 60% 且总数
超过 1,000”都只是 seed。校准应绑定现有 Context Pack 形态（16 个 Memory candidate、最多注入 8 项、caller byte
budget）以及实测 manifest size/write latency。

## L2：经过 Review 的语义维护

L2 是 RFC 0050 的受限 Memory 扩展。普通 Memory write 继续直接 commit，只有以下 maintenance proposal 进入 Review：

- **consolidation：**保留 evidence 的 revision 加 redundant-entry deactivation；
- **explicit supersession：**保留两条 entry，附加 successor/reason，使 predecessor 不再进入普通 current-state recall；
- **promotion：**把跨独立窗口反复出现的 working-note evidence 提升为长期 Memory kind。

每个 proposal 包含精确 pre-state identity、source/artifact evidence、relation/contradiction evidence、proposed change、
derived-view handling 与 policy version。只有 approval 才能创建对应 Memory Revision。推断关系必须 review；
consolidation 保留 evidence union 以及具体姓名、数字和日期；禁止在没有新 evidence 时反复“润色”正文。

L2 增加 Memory maintenance operation record，记录 operation identity、approved proposal identity、affected entries、
pre-state、created revision/relation、derived-view effect 和声明的 compensation behavior，并明确列出不可回滚效果。
它不同于 L1 recovery，也不同于 RFC 1557 的 Experience recurrence ledger；Memory L2 不得复用或重载该 ledger、
event semantic 或 Experience review route。任何 Memory Candidate/API 扩展都必须保持现有 Experience/Skill contract。

## Compression 与物理保留边界

本 RFC 不压缩或总结权威 Memory entry body。它们是自包含、可 citation 的记录；改写会损失姓名、日期、数量和
auditability。必须区分：

1. 权威 entry body：本 RFC 不 compact；
2. 可丢弃 derived view：后续设计可重新生成或 retire；
3. Topic Memory summary：属于独立 organization layer。

物理 tombstone/manifest compaction、legal retention、external erasure 和 cross-artifact cleanup 均不在本 RFC 范围。
#1425 负责更广的 policy boundary。Inventory 可以报告有界 active/inactive count、manifest growth 和 automatic-action
category，但不能据此授权删除。

## 兼容性、持久化与 API 影响

- 现有 Memory body、revision、manifest、evidence、search identity、Handoff citation 和公开 RRF score contract 不变。
- 新 lifecycle/quality data 是可重建 projection data 或有界 action evidence，不是 entry-body content。
- 首阶段 HTTP、MCP、CLI 和 OpenAPI shape 不变；Source adapter contract 是实现前置条件，不是隐式 `SourceRef` 推断。
- `CLAUDE.md`、`AGENTS.md` 等 project instruction file 仍是 source-authoritative、file-backed durable context，
  不受自动 Memory lifecycle 控制。
- 首次发布不通过 HTTP 暴露 ranking trace 或 lifecycle annotation；进程内 trace 不得为 observability 持久化正文。
- SQLite 与 OceanBase migration/rebuild 必须产生等价 projection state 与 order。
- #1321 的 append write amplification、storage layout、manifest split 和物理 compaction 不在本 RFC 范围。
- Lifecycle inventory 不得静默向 RFC 1557 引入的公开 `ScopeStats` contract 增加 field；公开 statistics API 扩展
  必须单独做兼容 contract 更新。

## 评测与校准

所有参数均为 seed。任何非中性默认值启用前必须完成：

1. **Quality benefit：**在相同 Context Pack byte budget 下比较 baseline 与 fixed-pool quality order，报告 Recall@k、
   MRR、answer/task outcome、latency 和 cost。
2. **Temporal validity：**同一 `entry_id` revise 后，普通 recall 只返回 current successor，精确历史读取仍返回
   predecessor 和 lifecycle reason。
3. **Conflict safety：**已知 inactive/superseded entry 不能到达 reranker 或 tool-using Context Pack；未知/不可比较
   conflict 保留并带标注。
4. **Candidate density：**固定必需 evidence，注入 near-duplicate/low-value record，测量 top-k degradation，校准
   relation threshold 与 bounded displacement。
5. **L1 dry run：**测量 false retirement、protection、restore、action idempotency 和 inbound-lineage handling。
6. **Longitudinal regression：**运行 Ledger-QA 形态的 revision sequence，同时按最终 task/world state 与 retrieval
   metric 评分 current-state 和“revision/time T 时为真”的回答。
7. **Safety：**把 provenance poisoning 与 low-authority/high-frequency-access case 和 relevance 分开评测。
8. **Recall-gate composition：**组合 FTS/vector/hybrid、reranker on/off、recall gate on/off，确认 quality reorder 保留
   每轮 reranker pool 的 member identity。
9. **Backend parity：**在 SQLite/OceanBase 运行 conformance 与 rebuild case，分别报告 retrieval、task、safety、cost。
10. **Full-context reference：**单独报告 full-material reference，避免把模型阅读失败误判成 retrieval/lifecycle 失败。

评测遵循 RFC 0080 和 RFC 1229 边界：PowerContext 暴露真实行为和 trace；workload、judge policy 与 acceptance
criteria 保持显式。Prior work 的结果只是 hypothesis，不是产品 acceptance threshold。

## 交付顺序

1. **Source 前置与中性 projection：**增加版本化 Source evidence declaration、lifecycle projection rebuild、内部
   annotation shape 和 conformance fixture；ranking 保持关闭。
2. **Stage-1 validity 与 fixed-pool ranking：**增加 current-state validity filter、`MemoryRankingTrace` 和默认关闭的
   `±2` reorder；保持 RFC 1560 recall-gate accounting 与 RFC 0080 reranker behavior。
3. **Alignment 与 L1：**增加有界 near-duplicate relation/proposal、inventory、tier 和 dry-run L1。
4. **L2 review：**单独交付 Memory Candidate/review integration、operation record、consolidation、explicit
   supersession 和 promotion；不与 RFC 1557 Experience recurrence work 耦合。
5. **Physical retention：**仅在 inventory 和评测证明存在 storage problem 时提出独立 RFC。

## 未来实现的验收标准

- 所有 lifecycle option 关闭时，write semantic、ranking、public contract 与 backend conformance 与当前行为一致。
- Importance、evidence strength、lifecycle observation 与 Source declaration 可从权威 revision 加精确、有界 operation
  evidence 重建，且都不改变 entry content hash。
- Low-importance entry 仍可参加普通 recall；只有显式或 policy deactivation 才将其移出 active candidate surface；
  `reactivate()` 恢复原 version，不创建新 body version。
- L1 只影响符合条件的 low-tier、expired、unprotected entry；记录 `auto_decay:v1`，支持 dry-run，可 audit、幂等、
  可恢复。Session-tier deactivation 记录 `session_end` 并可恢复。
- L2 proposal 在 approval 前不改变 authority；approved consolidation 保留 evidence lineage；explicit supersession
  保留新旧状态；unresolved conflict 保持可见且不推断时间顺序。
- Near-duplicate handling 不执行未验证的 semantic merge/discard；similarity finding 不会静默把 importance 降入
  deactivation floor。
- 普通 current-state recall 在 RRF/reranking 前过滤已知 inactive/superseded record；历史读取保留精确原件；
  unknown conflict 保持标注。
- Quality ordering 不改变 channel admission、固定 RRF pool membership、gate expansion policy 或公开 RRF score
  semantic；`MemoryRankingTrace` 使 validity 和 membership invariance 可审计。
- 评测在 SQLite/OceanBase 上报告 retrieval、task、safety、cost 和 backend parity，并包含 #1556/RFC 1560 matrix。

# 缺点

- Source authority/verification declaration 增加新的 adapter-contract 责任，需要谨慎迁移。
- 派生 projection、validity filtering 与 backend parity 增加实现和 conformance 复杂度。
- 校准不当时，即使 bounded reorder 也可能伤害相关 baseline rank，因此它必须很小且默认关闭。
- L1 可能错误停用很少使用但有价值的 low-importance entry；可恢复性只能降低、不能消除代价。
- L2 需要 reviewer 注意力和明确 compensation design，proposal 可能积压。
- Near-duplicate analysis 消耗 search/index work；无 embedding 时不能安全自动做 semantic decision。

# 理由与替代方案

- 拒绝 **multiplicative importance/decay weighting**：实际 RRF score range 会让 4 倍 multiplier 主导粗排，
  freshness 与 importance 相乘还可能降低长期 constraint。
- stage 1 拒绝 **quality before coarse truncation**：它会改变 reranker membership，需要独立实验、trace semantic
  和更广的 recall policy。
- 拒绝 **model importance score**：provider/time drift 使结果难以复现和测试。
- 拒绝 **automatic semantic deduplication/supersession**：similarity/relevance 不是破坏性 lifecycle change 的充分 evidence。
- 暂不使用 **temporal knowledge graph**：它会在 revisioned Memory 之外增加第二 authority 和大规模 schema。
- 拒绝 **body compaction**：它损害精确 citation，且不能解决 active-pool interference。
- 拒绝 **pure ACT-R decay**：usage-event power-law 机制不能由单一 timestamp 表达，也不适合通用 historical-fact policy。

# 先例

- [CoALA](https://arxiv.org/abs/2309.02427) 区分 working、episodic、semantic、procedural concern；本 RFC 采用
  operation separation，不引入新的 cognitive architecture。
- [MemGPT / Letta](https://www.letta.com/) 展示有界 in-context memory 与后台 consolidation；本 RFC 把
  consolidation 放在关键 read path 之外。
- [mem0 memory types](https://github.com/mem0ai/mem0/blob/main/docs/core-concepts/memory-types.mdx) 启发
  session/short/long time scale；其 [recency discussion](https://mem0.ai/blog/memory-decay-for-long-running-agents-how-recency-aware-ranking-fixes-retrieval-staleness)
  只为 query-gated freshness experiment 提供背景，不是 automatic deletion policy。
- [Generative Agents](https://arxiv.org/abs/2304.03442) 支持分离 relevance、recency、importance，但不支持导入
  free-form LLM score 或把 creation time 当 usage history。
- [ACT-R base-level learning](https://doi.org/10.1037/0033-295X.111.4.1036) 只启发未来 recall-event evaluation。
- [VoiceMem](https://arxiv.org/abs/2608.26005) 只支持 candidate-density hypothesis，不证明本 RFC freshness formula。
- [Revoked](https://arxiv.org/abs/2609.08258) 支持对已知 validity 做确定性 retrieval-time enforcement。
- [Selective Memory](https://arxiv.org/abs/2603.15994) 与 [ProMem](https://arxiv.org/abs/2601.04463) 支持可恢复
  retirement 和后续 alignment/verification，不支持未经 review 的 semantic deletion。
- [Rate–Distortion Theory for Agent Memory Compaction](https://arxiv.org/abs/2607.08032) 支持在统一 budget 下测量
  query 未知时不可逆丢弃的风险，不授权 body compaction。
- 提案人提供的补充背景见[资料 1](https://mp.weixin.qq.com/s/UDkGQvutJn-OQg0KunOqzw)、
  [资料 2](https://mp.weixin.qq.com/s/eijn2Cg3TSQqrqy2UU4fog) 和
  [资料 3](https://mp.weixin.qq.com/s/sQyuqmnl5EHMb-l356bFVQ)。这些资料只用于 memory organization/lifecycle
  讨论背景，不是 numeric default 或 acceptance threshold 的依据。

# 未解决问题

- 哪种 `MemoryEvidenceDeclaration` enum 与 registration mechanism 最适合 built-in/third-party Source adapter，
  同时保持可重建？
- 哪个显式 field 或 caller contract 用于把 Memory entry 分类为 current-state material？
- 首个 exact-revision path 之后是否需要公开 historical-read contract？
- 哪种 bounded rank-displacement mapping 能在校准 workload 中保持稳定收益？
- L2 Memory proposal 应扩展 generic Candidate family，还是使用专用 maintenance proposal type？
- 每种 approved L2 operation 与 derived view 可以采取哪些 compensation action？
- Inventory 可用后，哪些 physical-retention measurement 足以触发独立 compaction RFC？

# 未来可能性

- 异步、privacy-bounded recall-event projection，以及 authority-aware ACT-R-inspired feature。
- 用户可见 pin/protection control 与显式 lifecycle inspection。
- 公开且脱敏的 historical-read/lifecycle annotation API。
- 经过独立 review、具有显式 effective-time interval 的 temporal relation model。
- Topic-level derived summary，以及在测量证明必要时提出物理 manifest archival/compaction RFC。
