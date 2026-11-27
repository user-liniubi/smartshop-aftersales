from dataclasses import dataclass


@dataclass(frozen=True)
class DemoKnowledgeDocument:
    filename: str
    product_name: str | None = None
    category: str = "business_policy"


DEMO_KNOWLEDGE_DOCUMENTS = (
    DemoKnowledgeDocument("return_policy.md"),
    DemoKnowledgeDocument("warranty_policy.md"),
    DemoKnowledgeDocument("shipping_faq.md"),
    DemoKnowledgeDocument("after_sales_process.md", category="support_sop"),
    DemoKnowledgeDocument("delivery_damage.md"),
    DemoKnowledgeDocument("order_change_and_cancellation.md"),
    DemoKnowledgeDocument(
        "privacy_and_evidence_guide.md",
        category="support_sop",
    ),
    DemoKnowledgeDocument("discount_policy.md"),
    DemoKnowledgeDocument("after_sales_faq.pdf", category="support_sop"),
    DemoKnowledgeDocument("after_sales_faq_source.txt", category="support_sop"),
    DemoKnowledgeDocument(
        "headphones_manual.md",
        "SmartShop 降噪耳机 Pro",
        "product",
    ),
    DemoKnowledgeDocument(
        "headphones_troubleshooting.md",
        "SmartShop 降噪耳机 Pro",
        "product",
    ),
    DemoKnowledgeDocument(
        "keyboard_manual.md",
        "SmartShop 机械键盘 K87",
        "product",
    ),
    DemoKnowledgeDocument(
        "keyboard_troubleshooting.md",
        "SmartShop 机械键盘 K87",
        "product",
    ),
    DemoKnowledgeDocument(
        "monitor_manual.md",
        "SmartShop 27 英寸显示器",
        "product",
    ),
    DemoKnowledgeDocument(
        "monitor_troubleshooting.md",
        "SmartShop 27 英寸显示器",
        "product",
    ),
    DemoKnowledgeDocument(
        "laptop_manual.md",
        "SmartShop 14 英寸笔记本",
        "product",
    ),
    DemoKnowledgeDocument(
        "laptop_troubleshooting.md",
        "SmartShop 14 英寸笔记本",
        "product",
    ),
    DemoKnowledgeDocument(
        "mouse_manual.md",
        "SmartShop 无线鼠标 M2",
        "product",
    ),
    DemoKnowledgeDocument(
        "mouse_troubleshooting.md",
        "SmartShop 无线鼠标 M2",
        "product",
    ),
)
