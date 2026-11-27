# SmartShop AI P0 业务基础升级报告

> 完成日期：2026-11-23

## 完成内容

### 商品与售前

- 商品表新增结构化参数、实时价格、库存和上下架状态；
- 新增商品列表、搜索、详情和多商品对比 API；
- 售前聊天结合 MySQL 商品事实与商品知识 RAG 回答；
- 商品价格和库存不进入向量库。

### 订单履约

- 订单新增承运商、运单号、物流状态和更新时间；
- 物流查询复用本人订单权限和多订单候选确认；
- 物流事实只来自 MySQL 工具结果。

### 统一售后

- 工单新增 `repair` 维修类型；
- 维修复用售后资格、待审批工单、审批、取消和事件时间线；
- 聊天支持查询当前用户的售后进度；
- 质保期内维修可创建待审批工单，超保不自动认定免费维修。

### 统一意图

新增商品咨询、商品对比、优惠咨询、物流、维修和售后进度意图。所有意图继续使用同一会话、状态机、工具审计和人工接管体系。

### 前端

- 消费者首页增加商品价格库存、商品对比、物流和售后进度快捷入口；
- 客服端继续复用原有会话、人工接管和工单审批页面。

## 数据库

迁移：`a1c2e3f4b5d6_add_catalog_logistics_and_repair.py`

已在真实 MySQL 执行，并通过：

```text
alembic current: a1c2e3f4b5d6 (head)
alembic check: No new upgrade operations detected
```

## 验证

```text
uv run pytest -q
132 passed

ruff check .
All checks passed!

ruff format --check .
180 files already formatted
```

真实 API 验收：

```text
商品查询：SmartShop 降噪耳机 Pro
价格：899.00 CNY
库存：35
商品对比：2 个商品
商品咨询 action：answer
物流查询：订单 A10087 / 顺丰速运 / SFA10087 / in_transit
维修申请：ticket_created
工单号：AS-9B1C9EDCBB81
工单类型：repair
资格：eligible
退款金额快照：0.00
消费者取消：cancelled
```

Redis 开发端口调整为 `6381`，避免与本机已有的 6379、6380 服务冲突。

## 尚未完成

- P1 商家退款授权配置和 Agent 部分补偿决策；
- 售前优惠授权；
- 知识分类 metadata；
- 客服端商品与授权配置页面；
- 售前、履约和授权决策独立评测集。
