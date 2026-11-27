# SmartShop AI RAG 知识库设计说明

## 分类

| 分类 | 内容 |
|---|---|
| `product` | 商品介绍、参数、教程、FAQ、故障排查 |
| `business_policy` | 退换修、退款、质保、配送、优惠 |
| `support_sop` | 客服流程、证据规范、转人工条件 |

文档与 `Document`、`DocumentChunk`、`IngestionJob` 共用分类 metadata。

## 索引

```text
PDF / Markdown / TXT
→ 解析标题、章节和页码
→ 字符分块与重叠
→ BGE 向量
→ MySQL Chunk 映射
→ Chroma metadata
```

metadata 包含文档、Chunk、商品、分类、页码、标题和章节。

## 检索

```text
query embedding
→ product_id + category 过滤
→ 扩大候选集
→ 相似度阈值
→ 词面重合
→ 领域文件提示
→ 单文档多样性重排
→ Top-K 引用
```

## 拒答

低于相似度阈值、敏感越权查询或没有候选时返回无依据拒答，不调用回答模型。

## 不进入向量库的数据

- 实时价格；
- 实时库存；
- 订单状态；
- 物流状态；
- 用户身份和权限结果。

当前演示索引为 20 份文档、77 个 Chunk。P2 固定评测 RAG Hit@3/5 均为 1.0。
