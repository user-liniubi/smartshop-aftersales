# SmartShop AI API 接口说明

认证：

- `POST /auth/login`

会话与聊天：

- `POST /chat/sessions`
- `GET /chat/sessions`
- `POST /chat/sessions/{id}/messages`
- `POST /chat/sessions/{id}/order-selection`
- `POST /chat/sessions/{id}/handoff`

商品与订单：

- `GET /products`
- `GET /products/compare`
- `GET /orders/mine`
- `GET /orders/by-number/{order_no}`

售后：

- `GET /after-sales/tickets/mine`
- `GET/POST /after-sales/tickets/{id}/...`
- `GET /agent/after-sales/tickets`
- `POST /agent/after-sales/tickets/{id}/review`
- `POST /agent/after-sales/tickets/{id}/refund-execution/retry`

知识：

- `POST /knowledge/upload`
- `POST /knowledge/upload-async`
- `GET /knowledge/documents`
- `PATCH /knowledge/documents/{id}`
- `DELETE /knowledge/documents/{id}`

配置：

- `GET/POST/PATCH /agent/discounts/rules`
- `GET/POST/PATCH /agent/after-sales/refund-authorization-rules`
- `GET/PATCH /agent/catalog/products`
- `GET /agent/config/audit-logs`

RAG：

- `POST /api/v1/rag/ask`

所有受保护接口使用 Bearer Token。响应错误统一为 `{"error":{"code","message"}}`。
