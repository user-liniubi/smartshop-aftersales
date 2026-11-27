# SmartShop AI P2 系统完善报告

> 完成日期：2026-11-23

## 1. 完成范围

P2 在 P0 售前/履约/售后基础和 P1 退款授权闭环之上，完成：

- 售前优惠授权与模拟报价；
- 知识库三分类和 metadata 过滤；
- 混合检索重排；
- Agent 统一固定评测；
- 请求追踪与阶段耗时；
- 客服端商品、知识、优惠、补偿配置页面；
- 配置变更审计；
- Celery 异步索引队列路由；
- 完整 Docker Compose 部署；
- 最终交付文档。

## 2. 优惠授权

新增 `discount_authorization_rules` 和 `discount_quotes`。

优惠流程：

```text
用户询问优惠
→ DeepSeek 识别 discount_query
→ 商品工具查询 MySQL 标价和库存
→ 分类 RAG 检索优惠政策
→ 后端读取商品授权规则
→ 计算比例折扣与最高优惠金额
→ 生成 30 分钟有效模拟报价
→ 超过授权上限时转人工
```

关键边界：

- Agent 不能传入用户 ID；
- Agent 不能修改优惠规则；
- 优惠金额由后端确定性计算；
- 报价不创建订单、不锁库存、不代表支付成功；
- 无政策引用、无授权规则、商品下架或零库存时不生成报价。

演示规则：

| 商品 | 最高比例 | 最高金额 |
|---|---:|---:|
| 降噪耳机 Pro | 10% | 80 元 |
| 机械键盘 K87 | 8% | 40 元 |
| 27 英寸显示器 | 5% | 80 元 |
| 14 英寸笔记本 | 3% | 150 元 |
| 无线鼠标 M2 | 5% | 10 元 |

## 3. 知识分类与 RAG

知识分类：

- `product`：商品说明、参数、使用教程、故障排查；
- `business_policy`：退货、换货、退款、质保、配送和优惠；
- `support_sop`：客服流程、证据规范、人工转接和 FAQ。

当前真实索引：

```text
文档：20
Chunk/向量：77
业务政策：6 份
商品知识：10 份
客服 SOP：4 份
```

检索流程：

```text
问题
→ BGE query embedding
→ Chroma product_id + category 过滤
→ 候选扩大到 4 倍
→ 相似度
+ 词面重合
+ 领域文件提示
+ 同文档去重
→ Top-K 引用
```

商品实时价格、库存、订单和物流仍只从 MySQL 工具读取，不进入向量库。

## 4. 客服配置工作台

客服端新增“业务配置”页面：

- 商品说明、参数、价格、库存和上下架管理；
- 知识文档上传、分类调整、重建索引和删除；
- 售前优惠授权创建与修改；
- 售后补偿授权创建与修改；
- 配置变更审计记录。

所有配置接口要求客服角色。Agent 和消费者没有修改权限。

## 5. 评测结果

P2 固定评测集共 18 条，覆盖商品、对比、优惠、订单、物流、退换修、售后进度、缺失信息、越权、提示注入和无关问题。

首轮实际结果：

| 指标 | 首轮 | 最终 |
|---|---:|---:|
| 意图准确率 | 0.8889 | 1.0 |
| 动作准确率 | 0.8889 | 1.0 |
| 工具行为准确率 | 1.0 | 1.0 |
| RAG Hit@3 | 0.7273 | 1.0 |
| RAG Hit@5 | 0.7273 | 1.0 |
| 无依据拒答率 | 1.0 | 1.0 |
| 任务成功率 | 0.7222 | 1.0 |
| P50 | 1300.26 ms | 1254.26 ms |
| P95 | 35635.51 ms | 5801.16 ms |

首轮问题及修复：

- “参数和连接方式”被错误降级为售后政策，增加强商品事实关键词优先级；
- “我想申请售后”缺少类型，改为继续追问；
- 同一文件多个 Chunk 挤占 Top-K，增加文档多样性重排；
- 通用政策压过优惠、物流和换货文件，增加领域文件提示和词面重排；
- BGE 冷启动进入请求耗时，评测和 Docker 启动阶段执行预热。

评测报告：

- `data/eval/p2_2026-11-23/latest_report.json`
- `data/eval/p2_2026-11-23/latest_report.md`

## 6. 真实接口验收

授权内优惠：

```text
用户：降噪耳机能优惠50元吗？
action：answer
优惠金额：50.00 元
报价：849.00 CNY
引用：discount_policy.md
```

超额优惠：

```text
用户：降噪耳机能优惠100元吗？
授权上限：80.00 元
模拟报价：819.00 CNY
action：handoff_created
转人工原因：消费者期望优惠超过商家授权上限
```

请求观测：

```text
X-Request-ID: p2-smoke-0001
X-Process-Time-Ms: 7.51
```

## 7. 数据库与迁移

迁移：

```text
d4f5a6b7c8e9_add_p2_knowledge_discount_and_audit.py
```

新增能力：

- 文档与异步任务知识分类；
- 优惠授权规则；
- 优惠报价；
- 配置审计。

真实 MySQL 检查：

```text
alembic current = d4f5a6b7c8e9 (head)
alembic check = No new upgrade operations detected
```

## 8. 部署

Docker Compose 包含：

- MySQL 8；
- Redis 6；
- 初始化任务；
- FastAPI；
- Celery Worker；
- Streamlit 消费者端；
- Streamlit 客服端。

PyTorch 固定为 CPU 源，移除 CUDA/NVIDIA 依赖后镜像从数 GB 的 GPU 依赖集合降为实测约 1.08 GB。

验证：

```text
docker compose config --quiet：通过
docker compose build backend：通过
容器内应用导入：SmartShop AI
```

## 9. 自动化回归

```text
154 passed
All Ruff checks passed
210 files already formatted
uv lock --check passed
```

## 10. 当前边界

- 这是单商家客服系统，不是多商家 SaaS；
- 不创建订单、不收款、不接真实支付；
- 优惠报价和退款执行均为模拟业务；
- 18 条评测为固定小样本，不代表开放流量准确率；
- 客服配置工作台以单人管理员操作为主，未实现复杂角色分级和双人审批。
