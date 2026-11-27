# SmartShop AI 固定评测报告

## 指标

| 指标 | 结果 |
|---|---:|
| case_count | 18 |
| intent_accuracy | 1.0 |
| order_no_extraction_accuracy | 1.0 |
| action_accuracy | 1.0 |
| tool_behavior_accuracy | 1.0 |
| rag_hit_at_3 | 1.0 |
| rag_hit_at_5 | 1.0 |
| no_evidence_refusal_rate | 1.0 |
| task_success_rate | 1.0 |
| p50_latency_ms | 1254.26 |
| p95_latency_ms | 5801.16 |

## 分类结果

| 分类 | 成功 / 总数 |
|---|---:|
| after_sales_progress | 1 / 1 |
| discount | 3 / 3 |
| exchange | 1 / 1 |
| logistics | 1 / 1 |
| missing_info | 1 / 1 |
| order | 1 / 1 |
| product | 3 / 3 |
| product_usage | 1 / 1 |
| prompt_injection | 1 / 1 |
| repair | 1 / 1 |
| return | 1 / 1 |
| unauthorized | 1 / 1 |
| unrelated | 1 / 1 |
| warranty | 1 / 1 |

## 口径

- 意图和订单号使用 DeepSeek 结构化输出实测。
- 工具指标验证订单归属和未知工具拦截，不执行任意 SQL。
- RAG Hit@K 以人工标注的 gold files 是否进入前 K 条来源计算。
- RAG 使用生产链路的分类过滤、query expansion、领域文件提示和文档多样性重排。
- 任务成功率要求意图、订单号、工作流动作、工具行为以及适用的 RAG/拒答均正确。
- 该报告不包含最终回答人工正确率或引用支持度抽检。
