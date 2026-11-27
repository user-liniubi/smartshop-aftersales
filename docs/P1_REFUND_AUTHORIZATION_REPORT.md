# P1 退款授权与安全执行报告

## 1. 本阶段完成内容

P1 在已有售后状态机、对象级权限、订单工具、RAG 引用和人工接管能力之上，完成了“授权内补偿建议 → 审批 → 退款执行”的安全闭环。

核心原则：

1. DeepSeek 只提出结构化补偿建议，不直接退款；
2. 授权范围、可退余额、正数金额和置信度全部由后端校验；
3. 人工审批可以调整最终金额；
4. 审批与执行分别落库；
5. 当前接入的是确定性模拟退款网关，不连接真实支付渠道；
6. 执行请求使用固定幂等键，重复调用不会生成第二笔执行记录；
7. 失败退款最多重试 3 次，超过上限必须人工核查。

## 2. 数据模型

### `refund_authorization_rules`

保存商家定义的补偿场景和金额上下限：

- `scenario_code`
- `display_name`
- `min_amount`
- `max_amount`
- `version`
- `is_active`

### `agent_decisions`

保存 Agent 建议及后端校验结果：

- 建议金额；
- 可退余额快照；
- 置信度；
- 政策引用；
- 每项校验结果；
- `auto_approved`、`manually_approved`、`manual_review`、`rejected` 状态。

### `refund_executions`

保存审批后的退款执行事实：

- 工单和金额快照；
- 固定幂等键；
- `pending`、`success`、`failed` 状态；
- 模拟网关流水号；
- 尝试次数和失败原因；
- 请求时间、执行时间。

## 3. 审批规则

### 自动通过

以下条件必须全部成立：

- 场景存在；
- 金额位于商家授权上下限内；
- 金额不超过订单可退余额；
- 金额大于 0；
- 置信度不低于 0.80；
- 有满足条件且已被引用的政策证据。

任一项失败都会生成待人工审核工单。

### 人工通过

客服可以：

- 使用 Agent 建议金额；
- 输入新的最终金额；
- 查看订单可退余额、建议依据和每项校验结果；
- 拒绝并填写原因。

人工金额仍由后端再次校验：

- 必须大于 0；
- 不得超过该订单剩余可退余额；
- 最终金额写入工单；
- Agent 决策状态更新为 `manually_approved`。

## 4. 执行与重试

审批通过后，只有正数退款金额的工单才进入退款执行：

```text
审批通过
→ 生成固定幂等键
→ 创建 pending 执行记录
→ 调用模拟退款网关
→ success / failed
→ 写系统事件和聊天消息
```

失败后客服可调用重试接口，最多 3 次尝试。重复请求同一张已成功工单会直接返回原执行记录，不会重复退款。

## 5. API

- `GET /agent/after-sales/refund-authorization-rules`
- `POST /agent/after-sales/tickets/{ticket_id}/review`
- `GET /agent/after-sales/refund-executions/failed`
- `POST /agent/after-sales/tickets/{ticket_id}/refund-execution/retry`
- `GET /after-sales/tickets/mine`
- `GET /after-sales/tickets/{ticket_id}`

工单响应新增 `refund_execution`，消费者端可以看到执行状态、金额、尝试次数和失败原因。

## 6. 前端

消费者端：

- 展示最终退款金额；
- 展示执行成功、失败或待执行状态；
- 展示模拟退款流水号或失败原因。

客服端：

- 补偿工单显示 Agent 决策报告；
- 人工通过时可调整最终金额；
- 增加“退款执行”队列；
- 失败任务支持有限重试。

## 7. 验证结果

### 自动化测试

```text
142 passed
All Ruff checks passed
188 files already formatted
uv lock --check passed
alembic current = c3e4f5a6b7d8 (head)
alembic check = No new upgrade operations detected
```

新增覆盖：

- 人工审批最终金额落库；
- 人工金额超过可退余额被拦截；
- 已发生退款后剩余余额减少；
- 模拟退款执行成功；
- 固定幂等键防止重复执行；
- 临时失败后重试成功；
- 达到重试上限后停止；
- 客服查询失败任务并重试。

### 真实 MySQL + DeepSeek 验收

授权内自动审批：

```text
工单：AS-C347DA80ED9C
审批：auto_approved
金额：50.00 CNY
执行：success
流水：SIM-246940B1E510144F
```

人工调整金额后审批：

```text
工单：AS-E1C5BCDC8944
审批：manually_approved
最终金额：80.00 CNY
执行：success
流水：SIM-BC1E49210BA6677F
```

更新后的消费者回答示例：

```text
系统已在商家授权范围内通过部分补偿 20 CNY。
模拟退款执行成功，流水号 SIM-70BC0BD5A0C6F825。
```

## 8. 当前边界

- 退款网关为本地模拟实现，不会触发真实支付；
- 数据表保留执行状态和幂等键，后续可以替换为真实支付适配器；
- 授权规则的编辑与审计页面留到 P2；
- 商品、知识分类、优惠政策与完整评测集留到 P2。
