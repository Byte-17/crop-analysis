# 项目文件结构（代码生成前的蓝图）

```
mimo/
│
├── main.py                          # 系统入口：初始化、启动编排器
│
├── config/
│   ├── __init__.py
│   ├── settings.py                  # 系统全局配置（模型、预算、超参数）
│   └── agent_config.py              # 各智能体的独立配置（模型选择、触发规则）
│
├── core/                            # 核心调度与基础设施
│   ├── __init__.py
│   ├── orchestrator.py              # 编排器核心逻辑
│   │   ├── handle_user_input()      #    接收用户输入
│   │   ├── decompose_task()         #    任务分解
│   │   ├── dispatch()               #    调度子任务
│   │   ├── aggregate()              #    结果聚合
│   │   └── trigger_memory_save()    #    触发记忆存储
│   ├── scheduler.py                 # DAG 调度引擎
│   │   ├── build_dag()              #    构建依赖图
│   │   ├── resolve_order()          #    拓扑排序
│   │   ├── execute_parallel()       #    并行执行无依赖节点
│   │   └── execute_sequential()     #    串行执行有依赖节点
│   ├── token_estimator.py           # Token 预估器
│   │   ├── estimate()               #    主入口：E = B × P × C × D × S × M
│   │   ├── _calc_complexity()       #    计算 P
│   │   ├── _calc_context()          #    计算 C
│   │   ├── _calc_data_volume()      #    计算 D
│   │   ├── _get_base()              #    查表获取 B
│   │   └── _get_model_multiplier()  #    查表获取 M
│   ├── budget_manager.py            # 预算管理器
│   │   ├── check_budget()           #    校验预算
│   │   ├── apply_optimization()     #    触发优化模式
│   │   └── update_history()         #    更新历史消耗
│   ├── data_flow.py                 # 数据流定义与验证
│   │   ├── FlowRegistry             #    数据流注册表（F1~F14）
│   │   ├── validate_flow()          #    校验数据流格式
│   │   └── trace_flow()             #    追踪数据流路径
│   └── quality_controller.py        # 质量控制
│       ├── check_threshold()        #    评分阈值判断
│       ├── manage_retry()           #    重试管理
│       └── force_pass()             #    超限强制通过
│
├── agents/                          # 各智能体实现
│   ├── __init__.py
│   │
│   ├── base_agent.py                # 智能体基类（抽象类）
│   │   └── class BaseAgent          #    公共接口：process(), estimate_tokens()
│   │
│   ├── planner_agent.py             # 规划智能体
│   │   └── class PlannerAgent
│   │       ├── decompose_goal()     #        目标拆解
│   │       ├── define_milestones()  #        定义里程碑
│   │       └── identify_deps()      #        识别依赖关系
│   │
│   ├── researcher_agent.py          # 研究智能体
│   │   └── class ResearcherAgent
│   │       ├── search()             #        执行搜索
│   │       ├── extract_info()       #        信息提取
│   │       └── filter_and_score()   #        筛选与置信度标注
│   │
│   ├── analyst_agent.py             # 分析智能体
│   │   └── class AnalystAgent
│   │       ├── multi_dim_analysis() #        多维度分析
│   │       ├── detect_patterns()    #        模式识别
│   │       ├── cross_validate()     #        交叉验证
│   │       └── generate_insights()  #        生成结论
│   │
│   ├── writer_agent.py              # 写作智能体
│   │   └── class WriterAgent
│   │       ├── generate_content()   #        内容生成
│   │       ├── adapt_style()        #        风格适配
│   │       └── format_output()      #        格式化输出
│   │
│   ├── reviewer_agent.py            # 审查智能体
│   │   └── class ReviewerAgent
│   │       ├── check_completeness() #        完整性检查
│   │       ├── check_accuracy()     #        准确性检查
│   │       ├── check_logic()        #        逻辑性检查
│   │       ├── check_format()       #        格式检查
│   │       ├── check_style()        #        风格检查
│   │       └── score()              #        综合评分
│   │
│   └── memory_agent.py              # 记忆智能体
│       └── class MemoryAgent
│           ├── store()              #        记忆存储
│           ├── retrieve()           #        记忆检索（含评分）
│           └── get_context()        #        上下文增强
│
├── memory/                          # 记忆系统
│   ├── __init__.py
│   ├── store.py                     # 记忆存储层
│   │   ├── MemoryStore              #    记忆存储类
│   │   ├── save()                   #    写入记忆
│   │   ├── batch_save()             #    批量写入
│   │   └── delete()                 #    删除记忆
│   ├── retriever.py                 # 检索与相似度评分引擎
│   │   ├── MemoryRetriever          #    检索器类
│   │   ├── retrieve()               #    主检索函数
│   │   ├── calculate_similarity()   #    综合相似度计算
│   │   ├── _semantic_sim()          #    语义相似度（cosine）
│   │   ├── _topic_sim()             #    主题相似度
│   │   ├── _entity_sim()            #    实体相似度
│   │   ├── _recency_boost()         #    时间衰减提升
│   │   ├── _importance_boost()      #    重要性提升
│   │   └── _frequency_boost()       #    频率提升
│   ├── vectorizer.py                # 向量化服务
│   │   ├── Vectorizer               #    向量化接口
│   │   ├── embed_semantic()         #    语义嵌入
│   │   ├── embed_topic()            #    主题向量
│   │   └── extract_entities()       #    实体抽取
│   └── lifecycle.py                 # 记忆生命周期管理
│       ├── MemoryLifecycle          #    生命周期管理器
│       ├── merge_candidates()       #    查找可合并的记忆对
│       ├── merge()                  #    合并两条记忆
│       ├── find_expired()           #    查找过期记忆
│       ├── archive()                #    归档
│       └── purge()                  #    清理
│
├── models/                          # 数据模型（Pydantic/数据类）
│   ├── __init__.py
│   ├── task.py                      # 任务相关模型
│   │   ├── Task                     #    任务数据类
│   │   ├── TaskType                 #    任务类型枚举
│   │   └── TaskStatus               #    任务状态枚举
│   ├── plan.py                      # 计划相关模型
│   │   ├── Plan                     #    执行计划
│   │   ├── Step                     #    计划步骤
│   │   └── Dependency               #    步骤依赖
│   ├── message.py                   # 消息/数据流模型
│   │   ├── Message                  #    通用消息（F1~F14）
│   │   ├── FlowType                 #    数据流类型枚举
│   │   └── FlowPayload              #    各数据流的载荷定义
│   ├── memory_entry.py              # 记忆条目模型
│   │   ├── MemoryEntry              #    记忆条目
│   │   ├── MemoryType               #    记忆类型枚举
│   │   └── MemoryVectors            #    向量数据
│   ├── token_estimate.py            # Token 预估模型
│   │   ├── TokenEstimate            #    预估结果
│   │   └── TokenBudget              #    预算配置
│   └── review.py                    # 审查相关模型
│       ├── ReviewReport             #    审查报告
│       ├── ReviewDimension          #    评分维度
│       └── ReviewAction             #    处理动作枚举
│
├── storage/                         # 持久化层
│   ├── __init__.py
│   ├── base_store.py                # 存储抽象接口
│   │   └── class BaseStore          #    CRUD 接口
│   ├── file_store.py                # 文件系统存储
│   │   └── class FileStore          #    JSON/文件读写
│   ├── vector_store.py              # 向量存储适配器
│   │   └── class VectorStore        #    向量索引（可选 Chroma/LanceDB）
│   └── cache.py                     # 内存缓存层
│       └── class MemoryCache        #    LRU 缓存
│
├── utils/                           # 工具
│   ├── __init__.py
│   ├── logger.py                    # 日志工具
│   ├── timer.py                     # 计时器（性能监控）
│   └── serializer.py                # 序列化工具
│
├── tests/                           # 测试
│   ├── __init__.py
│   ├── test_token_estimator.py      # Token 预估测试
│   ├── test_memory_retriever.py     # 记忆检索测试
│   ├── test_scheduler.py            # 调度器测试
│   ├── test_quality_controller.py   # 质量控制测试
│   ├── test_data_flow.py            # 数据流测试
│   └── fixtures/
│       └── sample_memories.json     # 测试用记忆数据
│
└── requirements.txt                 # Python 依赖
```

---

## 文件依赖关系图

```
main.py
  └── core/orchestrator.py
        ├── core/scheduler.py
        ├── core/token_estimator.py
        ├── core/budget_manager.py
        ├── core/data_flow.py
        ├── core/quality_controller.py
        ├── agents/planner_agent.py
        ├── agents/researcher_agent.py
        ├── agents/analyst_agent.py
        ├── agents/writer_agent.py
        ├── agents/reviewer_agent.py
        └── agents/memory_agent.py
              └── memory/
                    ├── store.py
                    ├── retriever.py
                    ├── vectorizer.py
                    └── lifecycle.py
                          └── storage/
                                ├── base_store.py
                                ├── file_store.py
                                └── vector_store.py

models/  ← 被所有模块引用
config/  ← 被所有模块引用
utils/   ← 被所有模块引用
```

---

## 文件总数统计

| 层级 | 文件数 |
|------|--------|
| 根目录 | 2（main.py, requirements.txt） |
| config/ | 3 |
| core/ | 8 |
| agents/ | 8（含 base） |
| memory/ | 6 |
| models/ | 8 |
| storage/ | 5 |
| utils/ | 4 |
| tests/ | 6 |
| **总计** | **~50 个文件** |
