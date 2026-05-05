# CropAgent: Multi-Agent Agricultural Remote Sensing Pipeline

> 面向作物生长模拟与遥感分析的多智能体协作系统。支持批量地块处理、多步推理决策、记忆驱动的跨地块知识传播与 Token 感知调度。

---

## 系统架构

```
                  ┌──────────────────────────┐
                  │     CoordinatorAgent      │
                  │  (任务编排 / 调度 / 聚合)  │
                  └────┬──────┬──────┬───────┘
                       │      │      │
               ┌───────┘      │      └───────┐
               ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────────┐
        │DataAgent │   │ModelAgent│   │ReasoningAgent│
        │(NDVI/    │   │(LAI/SM/  │   │(异常检测 →    │
        │ NPMI)    │   │ ET)      │   │ 趋势分析 →    │
        └────┬─────┘   └────┬─────┘   │ 因果假设 →    │
             │              │         │ 决策输出)     │
             │              │         └──────┬───────┘
             │              │                │
             └──────┬───────┘                │
                    ▼                        ▼
             ┌──────────────────────────────────────┐
             │           MemorySystem                │
             │  (向量嵌入 + 余弦相似度 + Top-k 检索)  │
             │  (合并/遗忘生命周期管理)                 │
             └──────────────────────────────────────┘
```

每个地块的处理流水线：

```
Memory 检索 → DataAgent (遥感指数) → ModelAgent (作物模拟) → ReasoningAgent (推理决策) → Memory 存储
```

---

## 智能体职责

| 模块 | 职责 |
|------|------|
| **CoordinatorAgent** | 多地块编排，数据聚合，批量调度，跨地块对比报告 |
| **DataAgent** | 卫星遥感数据处理：计算 NDVI（归一化植被指数）、NPMI（归一化水分指数） |
| **ModelAgent** | 作物生长模拟：GDD（生长度日）驱动的 LAI、土壤水分、蒸散发逐日迭代 |
| **ReasoningAgent** | 四步推理链：异常检测 → 时序对比 → 因果假设 → 决策输出（含置信度） |
| **MemorySystem** | 45 维语义向量嵌入 + 余弦相似度检索 + 近邻合并 + 自适应遗忘 |
| **BatchPipeline** | 批量处理引擎，支持周期性内存合并与衰减，Token 累计追踪 |

---

## Token 消耗模型

采用 **`base + fields x steps x factor`** 动态计算公式（非硬编码常量）：

```
tokens = AGENT_BASE[agent] + fields x steps x factor
```

### 典型荷载估算

基于 55 地块 Sonnet 模型的实测数据：

| Agent | F (fields) | S (steps) | C (factor) | 单次调用 | 批量总量 |
|-------|-----------|-----------|------------|---------|---------|
| data_agent | 2 | 1 | 120 | 230 | 12,650 |
| model_agent | 3 | 120(天) | 1 | 480 | 26,400 |
| reasoning_agent | 5 | 4 | 120 | 2,520 | 138,600 |
| coordinator | 55 | 55 | 120 | 6,780 | 363,100 |
| memory | 1 | 1 | 120 | 200 | 11,000 |

**55 字段实测总量: ~554,835 tokens / 221 次调用**

### 在更大规模下的预计消耗

| 场景 | 字段数 | 推理步数 | 模型 | 预计 Token |
|------|--------|---------|------|-----------|
| 小规模试验 | 10 | 4 | Sonnet | ~120K |
| 中等规模 | 100 | 4 | Sonnet | ~1.0M |
| 省级监测 | 500 | 6 | Opus | ~8.5M |
| 区域持续运行(日) | 200 | 6 | Opus | ~3M - 8M |

---

## 实验案例

### 案例：新疆棉田灌溉决策模拟

**输入：** 模拟 Sentinel-2 时序影像（30 景，16 天重访周期）
**输出：** 灌溉时机推荐与水分胁迫评估

```
Field: F012-CoNA (Dry, Cotton, 150d)
  |-> data:    NDVI=+0.0053  NPMI=-0.0181
  |-> model:   LAI=4.72  ET=110mm  SM=56.0mm  stress=141d
  |-> reason:  normal (conf=0.522)  3 recs

Reasoning steps:
  Step 1 - Anomaly detection:  z-score outliers flagged
  Step 2 - Temporal comparison:  early/late split, trend analysis
  Step 3 - Causality:  soil_moisture -> NDVI correlation (r=0.78)
  Step 4 - Decision:  irrigation window DOY 130-135 recommended
```

**结果：** 检测到延迟覆膜模式，建议灌溉调整窗口：DOY 130-135，减少非生产性蒸散。

### 案例：批量气候对比（55 地块）

| 气候类型 | 地块数 | 平均置信度 | LAI 峰值 | ET 总量 |
|---------|-------|-----------|---------|--------|
| 温带 | 20 | 0.552 | 4.47 | 146mm |
| 热带 | 11 | 0.512 | 4.71 | 251mm |
| 干旱 | 24 | 0.527 | 4.64 | 97mm |

---

## 核心能力

- **多智能体编排** — CoordinatorAgent 协调 4 个专业智能体，支持任意规模的地块批处理
- **长链推理** — ReasoningAgent 四步推理链（异常→趋势→因果→决策），附带置信度和不确定性量化
- **记忆驱动** — MemorySystem 使用 45 维语义嵌入 + 余弦相似度，实现跨地块知识传播（首地块 0 条记忆 → 末地块 3+ 条）
- **批量扩展** — BatchPipeline 支持 100+ 地块处理，周期性内存合并（threshold=0.75），自适应衰减
- **Token 感知** — 基于 `base + fields x steps x factor` 的动态预估，支持预算管理和成本优化
- **全链路审计** — 每个智能体产生结构化日志，支持逐地块追溯

---

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/Byte-17/crop-analysis.git
cd crop-analysis

# 运行单模块测试
python tools/gee_mock.py           # GEE 模拟
python utils/token_tracker.py      # Token 追踪器
python agents/data_agent.py        # 遥感数据处理
python agents/model_agent.py       # 作物模型模拟
python agents/reasoning_agent.py   # 多步推理
python memory/memory_system.py     # 记忆系统
python agents/coordinator_agent.py # 编排器 + 跨字段对比

# 运行完整批处理演示
python examples/run_batch_demo.py
```

---

## 目录结构

```
crop-analysis/
├── agents/                  # 智能体实现
│   ├── data_agent.py       # NDVI / NPMI 时序计算
│   ├── model_agent.py      # GDD 驱动作物生长模型
│   ├── reasoning_agent.py  # 四步推理链引擎
│   └── coordinator_agent.py# 编排器 + 跨字段对比
├── tools/
│   └── gee_mock.py         # Google Earth Engine 模拟器
├── utils/
│   └── token_tracker.py    # Token 动态预估器
├── memory/
│   └── memory_system.py    # 向量记忆 + 相似度检索
├── workflows/
│   └── pipeline.py         # 批量处理流水线
├── examples/
│   └── run_batch_demo.py   # 演示入口
├── logs/
│   └── realistic_logs.txt  # 批处理日志输出
├── ARCHITECTURE.md         # 详细架构设计
├── FILE_STRUCTURE.md       # 文件结构与依赖图
└── README.md
```

---

## 未来工作

- **实时卫星数据接入** — 集成 Sentinel / Landsat 真实 API，替换 GEE 模拟层
- **API 服务化部署** — 封装 RESTful API，支持远程调用与异步任务队列
- **区域级扩展** — 扩展到省级 / 国家级农情监测，支持千级地块并行处理
- **多模态输入** — 融合气象站实测数据、土壤采样数据与卫星遥感
- **主动学习** — 利用 MemorySystem 的低置信度记忆触发自动重采样策略

---

## 许可证

MIT
