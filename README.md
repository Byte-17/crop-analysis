# MIMO 多智能体协作系统

> **M**ulti-agent **I**ntelligent **M**emory-driven **O**rchestration — 一种分层编排的多智能体协作框架。

---

## 概述

MIMO 是一个基于分层编排架构的多智能体协作系统。它通过一个统一的编排器（Orchestrator）调度多个专业智能体（Planner、Researcher、Analyst、Writer、Reviewer、Memory），协同完成复杂任务。

核心设计理念：

- **分工明确**：每个智能体专注单一职责，降低单智能体的复杂度
- **数据可追溯**：智能体之间的数据流清晰定义，每步可审计
- **记忆驱动**：跨会话的知识共享与上下文感知
- **质量闭环**：Reviewer 对输出进行多维度评分，低质量结果自动迭代
- **Token 可控**：基于公式的动态 Token 预估，支持预算管理与成本优化

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      用户接口层                          │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                     Orchestrator                         │
│              (任务分解 / 调度 / 聚合)                     │
└────┬──────┬──────┬──────┬──────┬──────┬─────────────────┘
     │      │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼      ▼
  Planner  Researcher Analyst  Writer Reviewer Memory
```

详细架构设计见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

---

## 智能体职责速览

| 智能体 | 职责 |
|--------|------|
| **Orchestrator** | 任务分解、智能体调度、结果聚合、Token 预算控制 |
| **Planner** | 将目标拆解为可执行步骤，定义里程碑和依赖关系 |
| **Researcher** | 外部信息收集、筛选与置信度标注 |
| **Analyst** | 多维度分析、模式识别、交叉验证 |
| **Writer** | 内容生成，根据受众调整风格 |
| **Reviewer** | 质量审查（完整性/准确性/逻辑性/格式/风格），决定是否迭代 |
| **Memory** | 记忆存储、相似度检索、合并与遗忘 |

---

## Token 预估模型

采用 **`fields × steps × factor`** 三因子乘积公式，不使用常数查表：

```
E = F × S × C
```

- **F** — Field Count：输入中需要处理的可数数据元素个数（如表单的字段数、文档的章节数）
- **S** — Step Count：任务在 Pipeline 中经过的 Stage 数量（含重试带来的额外步数）
- **C** — Coefficient：每字段每步的 Token 消耗基准，由模型决定（Sonnet=120, Opus=220）

详细公式和参数表见 [ARCHITECTURE.md](./ARCHITECTURE.md#4-token-预估逻辑)。

---

## 记忆系统

三层记忆架构 + 多维相似度评分：

| 层次 | 生命周期 | 用途 |
|------|----------|------|
| 短期记忆 | 单次会话 | 对话历史 |
| 工作记忆 | 单次会话 | 当前任务上下文 |
| 长期记忆 | 跨会话持久化 | 用户偏好、项目知识 |

相似度评分综合六维因素：

```
Sim = 0.40×语义 + 0.20×主题 + 0.15×实体 + 0.10×时间衰减 + 0.10×重要性 + 0.05×访问频率
```

详细记忆架构见 [ARCHITECTURE.md](./ARCHITECTURE.md#5-记忆系统设计)。

---

## 数据流

系统定义了 7 个 Pipeline Stage 共 14 条标准数据流（F1 ~ F14），覆盖从用户输入到最终输出的完整链路：

```
Stage 1 (Context Load):  F1~F3   User → Orchestrator → Memory
Stage 2 (Planning):      F4~F5   Orchestrator ↔ Planner
Stage 3 (Research):      F6~F7   Orchestrator ↔ Researcher
Stage 4 (Analysis):      F8~F9   Orchestrator ↔ Analyst
Stage 5 (Generation):    F10~F11 Orchestrator ↔ Writer
Stage 6 (Quality Gate):  F12~F13 Orchestrator ↔ Reviewer
Stage 7 (Output & Save): F14     Orchestrator → Memory
```

质量门禁不通过时触发 Stage 5 → Stage 6 循环迭代（最多 3 次）。

---

## 质量保证

Reviewer 从五个维度评分：

| 维度 | 权重 | 说明 |
|------|------|------|
| 完整性 | 30% | 是否覆盖所有要求 |
| 准确性 | 25% | 事实与数据是否准确 |
| 逻辑性 | 20% | 论证是否合理 |
| 格式规范 | 15% | 是否遵循格式要求 |
| 风格匹配 | 10% | 是否符目标受众 |

总分 ≥ 0.75 通过，< 0.75 触发迭代。

---

## 目录结构

```
mimo/
├── agents/              # 智能体实现
│   ├── orchestrator.py
│   ├── planner.py
│   ├── researcher.py
│   ├── analyst.py
│   ├── writer.py
│   ├── reviewer.py
│   └── memory.py
├── core/                # 核心框架
│   ├── scheduler.py     # 任务调度引擎（DAG）
│   ├── token_estimator.py  # Token 预估器
│   ├── data_flow.py     # 数据流定义与验证
│   └── budget_manager.py   # 预算管理器
├── memory/              # 记忆系统
│   ├── store.py         # 记忆存储层
│   ├── retriever.py     # 检索与评分引擎
│   ├── vectorizer.py    # 向量化
│   └── lifecycle.py     # 合并与遗忘策略
├── models/              # 数据模型
│   ├── task.py          # 任务模型
│   ├── plan.py          # 计划模型
│   ├── message.py       # 消息/数据流模型
│   └── memory_entry.py  # 记忆条目模型
├── storage/             # 持久化层
│   ├── file_store.py    # 文件存储
│   └── vector_store.py  # 向量数据库适配器
├── config/              # 配置
│   ├── settings.py      # 系统配置
│   └── agent_config.py  # 智能体配置
├── main.py              # 入口
└── requirements.txt     # 依赖
```

---

## 快速开始

```bash
# 克隆项目
git clone <repo-url>
cd mimo

# 安装依赖
pip install -r requirements.txt

# 配置
cp config/settings.example.py config/settings.py

# 运行
python main.py
```

---

## 扩展

新增智能体只需注册以下契约：

- `agent_id` — 唯一标识
- `input_schema` / `output_schema` — 输入输出格式定义
- `trigger_conditions` — 触发条件
- `token_estimator` — 可选的 Token 预估器

---

## 许可证

MIT
