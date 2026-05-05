# 多智能体协作系统 — 架构设计

## 1. 系统概述

本系统采用 **分层编排式多智能体架构（Layered Orchestration Architecture）**，由一个 **编排器（Orchestrator）** 统一调度多个专业智能体，各智能体分工明确、数据流清晰、记忆共享。

---

## 2. 智能体定义与职责

### 2.1 编排器智能体（Orchestrator Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 系统总控，任务入口与出口 |
| **职责** | ① 接收用户输入，进行任务意图识别与分解<br>② 将子任务分派给对应的专业智能体<br>③ 管理各智能体的执行顺序与并行策略<br>④ 聚合各智能体输出，形成最终响应<br>⑤ 监控 Token 消耗，触发预算控制 |
| **触发条件** | 每次用户消息首先到达编排器 |
| **输出** | 任务分解 DAG、最终聚合结果 |

### 2.2 规划智能体（Planner Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 战略层思考者 |
| **职责** | ① 将复杂目标拆解为可执行的步骤序列<br>② 定义里程碑与交付标准<br>③ 识别任务间的依赖关系<br>④ 生成执行计划（含预估 Token 开销） |
| **触发条件** | 编排器判定任务需要多步骤执行时 |
| **输出** | 结构化执行计划（JSON 格式步骤列表） |

### 2.3 研究智能体（Researcher Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 信息收集者 |
| **职责** | ① 执行 Web 搜索、文档查阅<br>② 从外部来源提取结构化信息<br>③ 对信息进行初步筛选与置信度标注<br>④ 返回引用来源 |
| **触发条件** | 任务需要外部知识或事实核查时 |
| **输出** | 信息摘要 + 来源引用列表 |

### 2.4 分析智能体（Analyst Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 深度处理者 |
| **职责** | ① 对研究结果进行多维度分析<br>② 识别模式、趋势、异常<br>③ 执行数据对比与交叉验证<br>④ 生成分析结论（含置信度评分） |
| **触发条件** | 研究智能体完成信息收集后，或需要处理结构化数据时 |
| **输出** | 分析报告（含数据可视化描述） |

### 2.5 写作智能体（Writer Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 内容生产者 |
| **职责** | ① 将分析结果转化为流畅的文本<br>② 根据目标受众调整语气与风格<br>③ 确保内容完整覆盖所有要求<br>④ 生成最终交付物（报告、方案、代码等） |
| **触发条件** | 分析智能体完成分析后，或需要生成内容时 |
| **输出** | 格式化内容（Markdown/HTML/代码等） |

### 2.6 审查智能体（Reviewer Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 质量守门员 |
| **职责** | ① 检查内容完整性（是否有遗漏要求）<br>② 校验事实准确性与逻辑一致性<br>③ 检查格式规范与风格统一<br>④ 给出修改建议与评分<br>⑤ 若评分低于阈值，打回给 Writer 重新生成 |
| **触发条件** | 写作智能体完成初稿后 |
| **输出** | 审查报告（评分 + 问题列表 + 修改建议） |

### 2.7 记忆智能体（Memory Agent）

| 属性 | 说明 |
|------|------|
| **角色** | 知识与上下文管理者 |
| **职责** | ① 管理长期记忆与短期记忆的存储与检索<br>② 执行记忆相似度评分，返回最相关记忆<br>③ 管理记忆的合并、过期与遗忘<br>④ 提供会话上下文增强 |
| **触发条件** | 任何智能体在开始工作前调用，获取相关记忆 |
| **输出** | 相关记忆片段列表（含相似度评分） |

---

## 3. Pipeline：七阶段流水线

整个系统是一个 **严格有序的七阶段流水线**，每个阶段接收上一阶段的输出，处理后传递给下一阶段。

```
                           Pipeline 数据流向
 ─────────────────────────────────────────────────────────────────────>

  Stage 1    →    Stage 2    →    Stage 3    →    Stage 4    →    Stage 5    →    Stage 6    →    Stage 7
 ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
 │Context │   │Planning│   │Research│   │Analysis│   │Writing │   │Quality │   │ Output │
 │ Load   │   │        │   │        │   │        │   │        │   │ Gate   │   │ & Save │
 └────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └───┬────┘   └────────┘
      │            │            │            │            │            │
      ▼            ▼            ▼            ▼            ▼            │
 Orchestrator  Orchestrator Orchestrator Orchestrator Orchestrator      │
      │            │            │            │            │            │
      ▼            ▼            ▼            ▼            ▼            │
    Memory       Planner    Researcher    Analyst       Writer         │
      │            │            │            │            │            │
      ▼            ▼            ▼            ▼            ▼            │
 Orchestrator  Orchestrator Orchestrator Orchestrator Orchestrator     │
                                                                       │
                                           ┌───────────────────────────┘
                                           │  ┌───── passed ────┐
                                           ▼  ▼                  │
                                       Reviewer ── failed ─── re-Writer
                                                                    │
                                                               (最多 3 次)
```

### 3.1 Stage 1 — 上下文加载（Context Loading）

```
输入: 用户原始消息
处理: Orchestrator 调用 Memory Agent 检索相关历史记忆
输出: 用户消息 + 相关记忆片段
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 1.1 | Orchestrator 接收用户输入 | `{ userId, message, sessionId }` |
| 1.2 | Orchestrator → Memory：检索相关记忆 | `{ query, topK: 5, threshold: 0.35 }` |
| 1.3 | Memory → Orchestrator：返回记忆片段 | `{ memories: [{ content, score }] }` |

### 3.2 Stage 2 — 规划（Planning）

```
输入: 用户消息 + 历史记忆
处理: Orchestrator 将目标发给 Planner 分解为可执行步骤
输出: 结构化执行计划（步骤列表 + 依赖关系）
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 2.1 | Orchestrator → Planner | `{ goal, constraints, memories }` |
| 2.2 | Planner 拆解目标、识别依赖 | 内部处理 |
| 2.3 | Planner → Orchestrator | `{ steps: [{ id, agent, input, dependsOn }] }` |

### 3.3 Stage 3 — 研究（Research）

```
输入: 研究任务描述
处理: Orchestrator 将研究任务发给 Researcher，收集外部信息
输出: 研究发现（含置信度评分）
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 3.1 | Orchestrator → Researcher | `{ queries, sources, context }` |
| 3.2 | Researcher 执行搜索、提取信息 | 内部处理 |
| 3.3 | Researcher → Orchestrator | `{ findings: [{ claim, source, confidence }] }` |

### 3.4 Stage 4 — 分析（Analysis）

```
输入: 研究发现
处理: Orchestrator 将数据发给 Analyst 进行多维度分析
输出: 分析结论（含模式识别和交叉验证结果）
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 4.1 | Orchestrator → Analyst | `{ data, dimensions, context }` |
| 4.2 | Analyst 分析数据、识别模式 | 内部处理 |
| 4.3 | Analyst → Orchestrator | `{ insights, patterns, conclusions }` |

### 3.5 Stage 5 — 写作（Generation）

```
输入: 分析结论 + 写作要求
处理: Orchestrator 将分析结果发给 Writer 生成最终内容
输出: 格式化内容初稿
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 5.1 | Orchestrator → Writer | `{ outline, references, style, format }` |
| 5.2 | Writer 生成内容 | 内部处理 |
| 5.3 | Writer → Orchestrator | `{ content, format, version }` |

### 3.6 Stage 6 — 质量门禁（Quality Gate）

```
输入: 内容初稿
处理: Orchestrator 将内容发给 Reviewer 进行多维度评分
      → 通过则进入 Stage 7
      → 不通过则返回 Stage 5，Writer 修改后再次审查
      → 最多迭代 3 次，超限则降级通过
输出: 合格的内容终稿
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 6.1 | Orchestrator → Reviewer | `{ content, criteria }` |
| 6.2 | Reviewer 多维度评分 | 内部处理 |
| 6.3 | Reviewer → Orchestrator | `{ score, dimensions, passed, suggestions }` |
| 6.4 | **if passed:** 进入 Stage 7 | |
| 6.5 | **if not passed:** 回 Stage 5.1（Writer）+ 增加 retry_count | 最多 3 次 |

### 3.7 Stage 7 — 输出与记忆保存（Output & Save）

```
输入: 合格的内容终稿
处理: Orchestrator 聚合结果返回给用户，同时将关键信息写入 Memory
输出: 最终回复 + 持久化的记忆条目
```

| 步骤 | 动作 | 数据 |
|------|------|------|
| 7.1 | Orchestrator → User | `{ response, metadata }` |
| 7.2 | Orchestrator → Memory（写） | `{ type, content, metadata }` |

### 3.8 数据流总览（F1 ~ F14）

```
F1:  User ──────────→ Orchestrator   (原始输入)
F2:  Orchestrator ──→ Memory         (记忆检索请求)
F3:  Memory ────────→ Orchestrator   (记忆检索结果)
F4:  Orchestrator ──→ Planner        (任务下发)
F5:  Planner ───────→ Orchestrator   (执行计划)
F6:  Orchestrator ──→ Researcher     (研究任务)
F7:  Researcher ────→ Orchestrator   (研究发现)
F8:  Orchestrator ──→ Analyst        (分析任务)
F9:  Analyst ───────→ Orchestrator   (分析结果)
F10: Orchestrator ──→ Writer         (写作任务)
F11: Writer ────────→ Orchestrator   (内容输出)
F12: Orchestrator ──→ Reviewer       (审查任务)
F13: Reviewer ──────→ Orchestrator   (审查结果)
F14: Orchestrator ──→ Memory         (记忆存储)
```

所有数据流均经过 Orchestrator 中转，编排器是唯一的枢纽节点。无任何智能体之间直接通信，确保数据流可追踪、可审计。

---

## 4. Token 预估逻辑

### 4.1 核心公式

Token 预估采用 **`fields × steps × factor`** 三因子乘积公式，不使用常数查表或经验值：

```
E = F × S × C
```

| 符号 | 含义 | 说明 |
|------|------|------|
| `F` | Field Count（字段数） | 输入数据中需要处理的可数数据元素个数 |
| `S` | Step Count（步数） | 当前任务在 Pipeline 中经过的 Stage 数量 |
| `C` | Coefficient（系数） | 每字段每步的基础 Token 消耗，由模型和任务复杂度决定 |

### 4.2 F — Field Count（字段数）

F 是输入数据中 **可数数据元素** 的数量，不同任务类型有不同的计数方式：

| 任务类型 | 一个字段的定义 | F 示例 |
|----------|---------------|--------|
| 表单处理 | 一个输入框/下拉框 = 1 field | 5 个字段的表单 → F=5 |
| 文档生成 | 一个章节/段落 = 1 field | 3 章 7 节 → F=10 |
| 数据分析 | 一个指标/维度 = 1 field | 销售额、利润、增长率 → F=3 |
| 代码生成 | 一个函数/模块 = 1 field | 3 个 API 函数 → F=3 |
| 质量审查 | 被审查内容的章节数 = 1 field | 5 个章节 → F=5 |
| 信息检索 | 一个搜索关键词 = 1 field | 3 个关键词 → F=3 |
| 对话回答 | 用户提到的诉求数 = 1 field | 2 个诉求 → F=2 |

**F 计算规则：**
```
F = max(1, count(data_elements))
```
- 至少为 1（即使没有任何结构化字段，整个输入算 1 个数据元素）
- 文档类任务按章节划分，不按字符数/单词数
- 复合输入取各来源 F 之和

### 4.3 S — Step Count（步数）

S 是 **当前任务在 Pipeline 中经过的 Stage 数量**，每个 Agent 调用算 1 step：

| Pipeline 路径 | S 值 |
|---------------|------|
| 最短路径（仅写作） | 1 |
| Research → Write | 2 |
| Research → Analyze → Write → Review | 4 |
| Plan → Research → Analyze → Write → Review | 5 |
| 完整路径（含 Memory）：Plan → Research → Analyze → Write → Review | 5 |
| 含 1 次迭代重试：额外 +2（re-Write + re-Review） | 7 |

**S 计算规则：**
```
S = pipeline_stage_count + 2 × retry_count
```
- 每增加一次 Review 迭代，S 增加 2（Writer 重写 + Reviewer 重审）
- 最大 S = 11（5 基础 + 2×3 最大重试）

### 4.4 C — Coefficient（系数）

C 是 **每字段每步的 Token 消耗基准**，由模型决定：

| 模型 | C 值（tokens/field/step） |
|------|--------------------------|
| Claude Sonnet | 120 |
| Claude Opus | 220 |
| GPT-4o | 180 |
| GPT-4o-mini | 70 |

C 为 **全量 Token（输入 + 输出）** 的复合成本，不再区分 in/out。

### 4.5 完整计算示例

**场景：** 用 Claude Sonnet 生成一份技术方案（3 个章节），走完整 Pipeline，不重试。

```
F = 3（3 个章节）
S = 5（Plan → Research → Analyze → Write → Review）
C = 120（Sonnet）

E = 3 × 5 × 120 = 1,800 tokens
```

**场景：** 用 Claude Opus 分析 5 个销售指标，走 Research → Analyze → Write，1 次重试。

```
F = 5（5 个指标）
S = 3（Research + Analyze + Write）+ 2（1 次重试）= 5
C = 220（Opus）

E = 5 × 5 × 220 = 5,500 tokens
```

**场景：** 简单问题回答，2 个诉求，仅触发 Writer，无重试。

```
F = 2
S = 1
C = 120（Sonnet）

E = 2 × 1 × 120 = 240 tokens
```

### 4.6 预算控制

```
预算上限:
  BUDGET_MAX = 100,000 tokens  (pipeline 级别硬限制)
  BUDGET_WARN =  50,000 tokens  (超过触发优化模式)

优化模式动作:
  E > BUDGET_WARN → 将模型降级为 mini（降低 C 值）
  E > BUDGET_MAX  → 拒绝执行，请求用户简化输入
```

### 4.7 与实际消耗的校准

每次任务完成后，记录实际 Token 消耗，反哺后续预估：

```
偏差率 δ = (实际消耗 - 预估消耗) / 预估消耗

if δ > 0.2:   C = C × 1.1    (低估了，提高系数)
if δ < -0.2:  C = C × 0.9    (高估了，降低系数)
```

C 值的校准范围为 `[0.5 × C_base, 2.0 × C_base]`，防止单次异常导致大幅波动。

---

## 5. 记忆系统设计

### 5.1 记忆层次

| 层次 | 存储位置 | 生命周期 | 容量 | 内容 |
|------|----------|----------|------|------|
| **短期记忆** | 内存（会话上下文） | 单次会话 | ~8K tokens | 当前对话历史、临时状态 |
| **工作记忆** | 内存（结构化缓存） | 单次会话 | ~2K tokens | 当前任务上下文、中间结果 |
| **长期记忆** | 文件/向量数据库 | 跨会话（持久化） | 无上限 | 用户偏好、关键决策、项目知识 |

### 5.2 记忆条目结构

```json
{
  "id": "mem_<uuid>",
  "type": "user_preference | project_knowledge | decision | interaction | task_result",
  "content": {
    "summary": "记忆内容摘要",
    "raw": "原始内容或引用",
    "key_entities": ["实体1", "实体2"]
  },
  "metadata": {
    "timestamp": "2026-05-05T10:30:00Z",
    "session_id": "session_xxx",
    "agent_type": "orchestrator | planner | ...",
    "task_id": "task_xxx",
    "importance": 0.0 ~ 1.0,
    "access_count": 0,
    "last_accessed": null
  },
  "vectors": {
    "semantic": [0.xxx, ...],     // 语义嵌入向量（128维）
    "topic": [0.xxx, ...],        // 主题分类向量（32维）
    "entity": [0.xxx, ...]        // 实体向量（64维）
  }
}
```

### 5.3 相似度评分公式

记忆检索时，计算查询与每条记忆的综合相似度：

```
Sim(q, m) = α × cos_sim(V_semantic(q), V_semantic(m))
           + β × cos_sim(V_topic(q), V_topic(m))
           + γ × cos_sim(V_entity(q), V_entity(m))
           + δ × recency_boost(m)
           + ε × importance_boost(m)
           + ζ × frequency_boost(m)
```

**权重默认值：**

| 参数 | 权重 | 说明 |
|------|------|------|
| α | 0.40 | 语义相似度 — 最重要维度 |
| β | 0.20 | 主题相似度 |
| γ | 0.15 | 实体重叠度 |
| δ | 0.10 | 时间衰减提升（越近越高） |
| ε | 0.10 | 重要性提升 |
| ζ | 0.05 | 访问频率提升 |

**各提升函数定义：**

```
recency_boost(m) = e^(-0.1 × days_since_access(m))
  → 最近 1 天：0.905
  → 最近 7 天：0.497
  → 最近 30 天：0.050

importance_boost(m) = metadata.importance
  → 由记忆写入时的智能体评估

frequency_boost(m) = tanh(access_count / 10)
  → 访问 1 次：0.100
  → 访问 5 次：0.462
  → 访问 10 次：0.762
  → 访问 20 次：0.964
```

### 5.4 相似度评分计算示例

下面用一个具体例子展示相似度评分如何运作，证明这不是字典查表。

**查询：** 用户问 "我们团队上次的微服务迁移方案有什么经验教训？"
→ 提取查询向量：`V_semantic(q)`, `V_topic(q)`, `V_entity(q)`

**记忆库中的 4 条候选记忆：**

| ID | 内容摘要 | 向量相似度 | 天数 | 重要性 | 访问次数 |
|----|---------|-----------|------|--------|---------|
| m1 | "微服务迁移采用Strangler Fig模式，分三期完成" | semantic=0.82, topic=0.75, entity=0.90 | 3天前 | 0.8 | 12 |
| m2 | "Q3前端技术选型讨论：React vs Vue" | semantic=0.25, topic=0.30, entity=0.10 | 10天前 | 0.4 | 3 |
| m3 | "用户偏好：方案文档需要包含架构图" | semantic=0.45, topic=0.50, entity=0.30 | 30天前 | 0.6 | 1 |
| m4 | "数据库分库分表方案评审：按用户ID哈希" | semantic=0.55, topic=0.60, entity=0.20 | 1天前 | 0.7 | 5 |

**逐条计算 Sim(q, m)：**

```
m1:
  cos_sem = 0.82, cos_topic = 0.75, cos_entity = 0.90
  recency = e^(-0.1×3) = 0.741
  importance = 0.8
  frequency = tanh(12/10) = 0.832

  Sim = 0.40×0.82 + 0.20×0.75 + 0.15×0.90 + 0.10×0.741 + 0.10×0.8 + 0.05×0.832
      = 0.328 + 0.150 + 0.135 + 0.074 + 0.080 + 0.042
      = 0.809

m2:
  cos_sem = 0.25, cos_topic = 0.30, cos_entity = 0.10
  recency = e^(-0.1×10) = 0.368
  importance = 0.4
  frequency = tanh(3/10) = 0.291

  Sim = 0.40×0.25 + 0.20×0.30 + 0.15×0.10 + 0.10×0.368 + 0.10×0.4 + 0.05×0.291
      = 0.100 + 0.060 + 0.015 + 0.037 + 0.040 + 0.015
      = 0.267

m3:
  cos_sem = 0.45, cos_topic = 0.50, cos_entity = 0.30
  recency = e^(-0.1×30) = 0.050
  importance = 0.6
  frequency = tanh(1/10) = 0.100

  Sim = 0.40×0.45 + 0.20×0.50 + 0.15×0.30 + 0.10×0.050 + 0.10×0.6 + 0.05×0.100
      = 0.180 + 0.100 + 0.045 + 0.005 + 0.060 + 0.005
      = 0.395

m4:
  cos_sem = 0.55, cos_topic = 0.60, cos_entity = 0.20
  recency = e^(-0.1×1) = 0.905
  importance = 0.7
  frequency = tanh(5/10) = 0.462

  Sim = 0.40×0.55 + 0.20×0.60 + 0.15×0.20 + 0.10×0.905 + 0.10×0.7 + 0.05×0.462
      = 0.220 + 0.120 + 0.030 + 0.091 + 0.070 + 0.023
      = 0.554
```

**排序与过滤结果：**

| 排名 | ID | 相似度 | 阈值 0.35 | 是否返回 |
|------|----|--------|-----------|---------|
| 1 | m1 | **0.809** | ✅ | ✅ Top-1 |
| 2 | m4 | **0.554** | ✅ | ✅ Top-2 |
| 3 | m3 | **0.395** | ✅ | ✅ Top-3 |
| 4 | m2 | **0.267** | ❌ 低于阈值 | ❌ 丢弃 |

**结论：** 返回 m1、m4、m3 三条记忆给 Orchestrator，其中 m1（微服务迁移经验）与用户查询高度相关（0.809），m2（前端技术选型）完全不相关被过滤掉。

### 5.5 检索策略

```
1. 从长期记忆中取出候选集 Top-K 条（K=20）
2. 对每条计算 Sim(q, m)（使用 5.3 的六维公式）
3. 过滤低于阈值（默认 θ=0.35）的记忆
4. 按 Sim 降序排列
5. 取前 N 条（N=5）返回给调用智能体
6. 更新被命中记忆的 access_count += 1 和 last_accessed = now
```

### 5.6 记忆合并与遗忘

**合并触发条件：** 当两条记忆满足以下条件时自动合并：
- Sim(m1, m2) > 0.85
- 且 type 相同
- 且 key_entities 重叠 > 50%

**遗忘策略：**
- 每条记忆有 `ttl`（生存时间），默认 90 天
- 超过 TTL 且 `importance < 0.3` 的记忆进入"待归档"状态
- 归档记忆压缩存储，检索时最后考虑
- 超过 180 天且 `importance < 0.2` 自动删除

---

## 6. 质量保证机制

### 6.1 Reviewer 评分维度

| 维度 | 权重 | 评分范围 |
|------|------|----------|
| 完整性 | 30% | 0~1.0 |
| 准确性 | 25% | 0~1.0 |
| 逻辑性 | 20% | 0~1.0 |
| 格式规范 | 15% | 0~1.0 |
| 风格匹配 | 10% | 0~1.0 |

```
总分 = Σ (维度得分 × 维度权重)
通过阈值: ≥ 0.75
```

### 6.2 重试策略

```
if 总分 >= 0.75:
    通过，进入下一阶段
elif 总分 >= 0.50:
    标记"修改建议"，打回 Writer 迭代
else:
    标记"重写"，打回 Planner 重新规划

最大迭代次数: 3
超过最大迭代: 强制通过并附加"质量预警"标签
```

---

## 7. 扩展性设计

### 7.1 新增智能体

只需满足以下契约即可注册新智能体：

```json
{
  "agent_id": "custom_agent",
  "input_schema": { /* JSON Schema 定义输入格式 */ },
  "output_schema": { /* JSON Schema 定义输出格式 */ },
  "trigger_conditions": "关键字匹配 | 任务类型匹配 | 编排器路由",
  "token_estimator": "可选，默认使用基础公式 × 自定义系数"
}
```

### 7.2 并行执行

编排器支持 DAG 调度，无依赖关系的智能体可并行执行：

```
例如：
   Planner ──┬── Researcher ──┐
             ├── Analyst      ├── Writer
             └── Memory       ┘
其中 Researcher、Analyst、Memory 可并行
```
