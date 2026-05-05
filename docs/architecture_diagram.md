# 系统架构图

```mermaid
graph TB
    %% 顶层：数据源
    subgraph Input["数据输入层"]
        S1["Sentinel-2 / Landsat<br/>时序影像"]
        C1["气象数据<br/>(温度 / 降水)"]
        F1["田块配置<br/>(作物 / 种植日期 / 区域)"]
    end

    %% 编排层
    subgraph CO["CoordinatorAgent 编排调度"]
        CO1["任务分解<br/>F1-F14 数据流"]
        CO2["Memory 检索<br/>历史知识"]
        CO3["结果聚合<br/>跨田块对比"]
    end

    %% Agent 层
    subgraph DA["DataAgent 数据感知"]
        DA1["影像筛选<br/>云掩膜 / 窗口优化"]
        DA2["NDVI 计算<br/>(B5-B4)/(B5+B4)"]
        DA3["NPMI 计算<br/>(B5-B6)/(B5+B6)"]
    end

    subgraph MA["ModelAgent 机理建模"]
        MA1["逐日 GDD 计算<br/>积温驱动"]
        MA2["LAI 生长模拟<br/>Logistic 增长"]
        MA3["土壤水分平衡<br/>降雨 - 蒸散 - 排水"]
        MA4["蒸散发估算<br/>PET x Kc x Stress"]
    end

    subgraph RA["ReasoningAgent 推理决策"]
        RA1["Step 1: 异常检测<br/>Z-score / 突变识别"]
        RA2["Step 2: 时序对比<br/>早期 / 后期趋势"]
        RA3["Step 3: 因果假设<br/>Pearson 相关性"]
        RA4["Step 4: 决策输出<br/>置信度 + 建议"]
    end

    subgraph MEM["MemorySystem 记忆系统"]
        MEM1["45维语义嵌入<br/>MD5 哈希映射"]
        MEM2["余弦相似度检索<br/>Top-K 排序"]
        MEM3["记忆合并<br/>(threshold >= 0.75)"]
        MEM4["自适应遗忘<br/>(重要性 / 访问频率)"]
    end

    subgraph TOKEN["TokenTracker 消耗追踪"]
        T1["base + fields x steps x factor<br/>动态公式"]
        T2["按 Agent 汇总"]
        T3["按模型对比<br/>Sonnet / Opus / Haiku"]
    end

    %% 数据流连接
    S1 --> DA1
    C1 --> MA1
    F1 --> CO1

    CO1 --> DA1
    CO1 --> MA1
    CO1 --> RA1

    DA1 --> DA2 --> DA3
    MA1 --> MA2 --> MA3 --> MA4

    DA3 --> RA1
    MA4 --> RA1
    RA1 --> RA2 --> RA3 --> RA4

    CO2 --> MEM1 --> MEM2 --> CO1
    RA4 --> CO3
    CO3 --> MEM3 --> MEM4

    TOKEN -.-> DA
    TOKEN -.-> MA
    TOKEN -.-> RA
    TOKEN -.-> CO

    %% 样式
    classDef input fill:#e1f5fe,stroke:#0288d1
    classDef coord fill:#fff3e0,stroke:#f57c00
    classDef data fill:#e8f5e9,stroke:#388e3c
    classDef model fill:#fce4ec,stroke:#c62828
    classDef reason fill:#f3e5f5,stroke:#6a1b9a
    classDef memory fill:#fbe9e7,stroke:#d84315
    classDef token fill:#e0f2f1,stroke:#00695c

    class S1,C1,F1 input
    class CO,CO1,CO2,CO3 coord
    class DA,DA1,DA2,DA3 data
    class MA,MA1,MA2,MA3,MA4 model
    class RA,RA1,RA2,RA3,RA4 reason
    class MEM,MEM1,MEM2,MEM3,MEM4 memory
    class TOKEN,T1,T2,T3 token
```

---

## 处理流水线（每田块）

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐
│ Memory   │ -> │  Data    │ -> │  Model   │ -> │  Reasoning   │ -> │  Memory  │
│ Retrieve │    │  Agent   │    │  Agent   │    │  Agent       │    │  Store   │
└──────────┘    └──────────┘    └──────────┘    └──────────────┘    └──────────┘
     │              │              │                    │                │
     │ 过去知识      │ NDVI/NPMI    │ LAI/SM/ET          │ 异常/趋势/     │ 结果持久化
     │ 跨田块复用    │ 时序         │ 模拟                │ 因果/决策      │
```

---

## 各阶段输入/输出

| 阶段 | 输入 | 输出 | Token 公式 |
|------|------|------|-----------|
| Memory Retrieve | 查询文本（作物+气候+区域） | 相似记忆列表 (score, content) | 80 + 1x1x120 = 200 |
| DataAgent | ImageCollection(30 images) | NDVI、NPMI 时序 (date, value) | 150 + 2x1x120 = 390 |
| ModelAgent | 种植日期、天数、气候 | LAI/SM/ET 逐日记录、汇总统计 | 100 + 3x120x1 = 460 |
| ReasoningAgent | 5 条变量时序 | 异常检测、趋势、因果假设、决策建议 | 180 + 5x4x120 = 2,580 |
| Memory Store | 分析结果 + 决策 | 嵌入 + 存储 + 合并 + 衰减 | 80 + 1x1x120 = 200 |

---

## Token 消耗模式

```
单田块:          ~200 + 390 + 460 + 2,580 + 200 = ~3,830 tokens
55 田块批量实测:  554,835 tokens / 221 次调用 / 3.8s
日预测(200田块):  ~3M - 8M tokens (Sonnet / Opus)
```

---

## 核心设计要点

1. **Token = base + fields x steps x factor** — 不使用常量，每一步可审计
2. **Memory 不是字典** — 45 维语义嵌入 + 余弦相似度 + Top-K 排序检索
3. **推理不是 if-else** — 四步长链：统计异常 → 线性趋势 → Pearson 因果 → 结构化决策
4. **批量可扩展** — 55 田块 3.8s 完成，支持 `consolidate_every` 周期性合并
