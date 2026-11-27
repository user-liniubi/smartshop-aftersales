import json

import streamlit as st

try:
    from frontend.api_client import ApiClient, ApiError
    from frontend.login_ui import render_login_screen
    from frontend.ui import (
        after_sales_ticket_status_label,
        after_sales_ticket_type_label,
        agent_decision_status_label,
        format_timestamp,
        handoff_status_label,
        inject_styles,
        refund_execution_status_label,
        render_message,
        render_order_card,
        render_session_meta,
        status_label,
        workflow_label,
    )
except ModuleNotFoundError:
    from api_client import ApiClient, ApiError
    from login_ui import render_login_screen
    from ui import (
        after_sales_ticket_status_label,
        after_sales_ticket_type_label,
        agent_decision_status_label,
        format_timestamp,
        handoff_status_label,
        inject_styles,
        refund_execution_status_label,
        render_message,
        render_order_card,
        render_session_meta,
        status_label,
        workflow_label,
    )

SOURCE_LABELS = {
    "user": "消费者申请",
    "ai": "AI 降级",
    "rule": "规则触发",
}

st.set_page_config(
    page_title="SmartShop AI · 客服工作台",
    page_icon=":material/support_agent:",
    layout="wide",
)

st.session_state.setdefault("agent_token", None)
st.session_state.setdefault("agent_user", None)
st.session_state.setdefault("agent_view", "待接管")
st.session_state.setdefault("agent_switch_to_mine", False)


def logout() -> None:
    st.session_state.agent_token = None
    st.session_state.agent_user = None
    st.session_state.pop("agent_handoff_id", None)


def client() -> ApiClient:
    return ApiClient(token=st.session_state.agent_token)


def show_error(error: ApiError) -> None:
    st.error(error.message, title="操作失败")


def render_after_sales_ticket_workspace() -> None:
    try:
        tickets = client().list_pending_after_sales_tickets()
    except ApiError as error:
        show_error(error)
        return

    ticket_by_id = {ticket["id"]: ticket for ticket in tickets}
    if st.session_state.get("agent_ticket_id") not in ticket_by_id:
        st.session_state.agent_ticket_id = tickets[0]["id"] if tickets else None
    selected_id = st.session_state.get("agent_ticket_id")
    selected = ticket_by_id.get(selected_id) if selected_id is not None else None

    left, center, right = st.columns([0.2, 0.3, 0.5], gap="medium")
    with left:
        with st.container(key="agent-nav"):
            st.markdown("### :material:support_agent: 工单审批")
            st.caption("AI 已核验订单和政策，等待人工决定。")
            if st.button(
                "返回客服会话",
                icon=":material/arrow_back:",
                width="stretch",
            ):
                st.session_state.agent_view = "待接管"
                st.rerun()
            st.caption(f"待审批 {len(tickets)} 张")

    with center:
        with st.container(key="agent-list"):
            st.markdown("### 待审批工单")
            if not tickets:
                st.info("当前没有待审批售后工单。", title="审批队列为空")
            else:
                for ticket in tickets:
                    ticket_id = ticket["id"]
                    is_selected = ticket_id == selected_id
                    with st.container(key=f"agent-ticket-{ticket_id}"):
                        if st.button(
                            ticket["ticket_no"],
                            key=f"select-agent-ticket-{ticket_id}",
                            type="primary" if is_selected else "secondary",
                            width="stretch",
                        ):
                            st.session_state.agent_ticket_id = ticket_id
                            st.rerun()
                        st.caption(
                            f"{after_sales_ticket_type_label(ticket['request_type'])}"
                            f" · {after_sales_ticket_status_label(ticket['status'])}"
                        )
                        st.caption(
                            f"会话 #{ticket['session_id']} · "
                            f"{format_timestamp(ticket['created_at'])}"
                        )

    with right:
        with st.container(key="agent-chat"):
            if selected is None:
                st.info("从待审批列表选择一张工单。", title="尚未选择工单")
                return
            st.markdown(f"### {selected['ticket_no']}")
            st.caption(
                f"{after_sales_ticket_type_label(selected['request_type'])}"
                f" · {after_sales_ticket_status_label(selected['status'])}"
            )
            st.markdown(f"**问题描述**  \n{selected['issue_description']}")
            st.caption(
                f"消费者 #{selected['user_id']} · 订单 #{selected['order_id']}"
                f" · 会话 #{selected['session_id']}"
            )
            citations = selected.get("policy_citations") or []
            if citations:
                with st.expander("查看政策依据", icon=":material/menu_book:"):
                    for citation in citations:
                        st.markdown(
                            f"**{citation.get('title', '知识片段')}** "
                            f"· `{citation.get('filename', '')}`"
                        )
                        st.caption(citation.get("excerpt", ""))

            decision = selected.get("agent_decision")
            if decision:
                st.markdown("#### Agent 退款决策报告")
                st.caption(
                    f"场景：{decision.get('scenario_code')} · "
                    f"{agent_decision_status_label(decision.get('decision_status', ''))}"
                )
                st.markdown(
                    f"**建议金额：** {decision.get('suggested_amount')} "
                    f"{selected.get('currency', 'CNY')}"
                )
                st.markdown(
                    f"**授权范围：** {decision.get('authorization_min')} ～ "
                    f"{decision.get('authorization_max')} "
                    f"{selected.get('currency', 'CNY')}"
                )
                st.caption(
                    f"可退余额：{decision.get('available_amount')} · "
                    f"置信度：{decision.get('confidence')}"
                )
                st.markdown(f"**分析依据：** {decision.get('analysis', '')}")
                with st.expander("查看后端校验明细"):
                    st.json(decision.get("validation") or {})

            final_refund_amount: str | None = None
            if selected["request_type"] == "compensation":
                suggested_amount = decision.get("suggested_amount") if decision else None
                default_amount = max(0.01, float(suggested_amount or 0.01))
                reviewed_amount = st.number_input(
                    "最终补偿金额",
                    min_value=0.01,
                    value=default_amount,
                    step=0.01,
                    format="%.2f",
                    help="金额不得超过订单当前可退余额。",
                    key=f"ticket-refund-amount-{selected['id']}",
                )
                final_refund_amount = f"{reviewed_amount:.2f}"

            review_note = st.text_area(
                "审批意见",
                max_chars=500,
                placeholder="拒绝时必须填写原因；通过时可选填。",
                key=f"ticket-review-note-{selected['id']}",
            )
            approve_column, reject_column = st.columns(2)
            with approve_column:
                if st.button(
                    "通过工单",
                    icon=":material/task_alt:",
                    type="primary",
                    width="stretch",
                ):
                    try:
                        client().review_after_sales_ticket(
                            selected["id"],
                            decision="approved",
                            review_note=review_note.strip(),
                            refund_amount=final_refund_amount,
                        )
                        st.rerun()
                    except ApiError as error:
                        show_error(error)
            with reject_column:
                if st.button(
                    "拒绝工单",
                    icon=":material/cancel:",
                    width="stretch",
                ):
                    if not review_note.strip():
                        st.warning("拒绝工单时必须填写审批意见。")
                    else:
                        try:
                            client().review_after_sales_ticket(
                                selected["id"],
                                decision="rejected",
                                review_note=review_note.strip(),
                            )
                            st.rerun()
                        except ApiError as error:
                            show_error(error)


def render_refund_execution_workspace() -> None:
    try:
        executions = client().list_failed_refund_executions()
    except ApiError as error:
        show_error(error)
        return

    execution_by_ticket = {item["ticket_id"]: item for item in executions}
    if st.session_state.get("agent_execution_ticket_id") not in execution_by_ticket:
        st.session_state.agent_execution_ticket_id = (
            executions[0]["ticket_id"] if executions else None
        )
    selected_id = st.session_state.get("agent_execution_ticket_id")
    selected = execution_by_ticket.get(selected_id) if selected_id is not None else None

    left, center, right = st.columns([0.2, 0.3, 0.5], gap="medium")
    with left:
        with st.container(key="agent-nav"):
            st.markdown("### :material/payments: 退款执行")
            st.caption("审批与退款执行分离，失败任务可有限重试。")
            if st.button(
                "返回客服会话",
                icon=":material/arrow_back:",
                width="stretch",
            ):
                st.session_state.agent_view = "待接管"
                st.rerun()
            st.caption(f"执行失败 {len(executions)} 笔")

    with center:
        with st.container(key="agent-list"):
            st.markdown("### 失败任务")
            if not executions:
                st.info("当前没有退款执行失败任务。", title="执行队列正常")
            else:
                for execution in executions:
                    is_selected = execution["ticket_id"] == selected_id
                    if st.button(
                        execution["ticket_no"],
                        key=f"select-refund-execution-{execution['ticket_id']}",
                        type="primary" if is_selected else "secondary",
                        width="stretch",
                    ):
                        st.session_state.agent_execution_ticket_id = execution["ticket_id"]
                        st.rerun()
                    st.caption(
                        f"{execution['amount']} {execution['currency']} · "
                        f"{refund_execution_status_label(execution['status'])}"
                    )

    with right:
        with st.container(key="agent-chat"):
            if selected is None:
                st.info("从失败列表选择一笔退款任务。", title="尚未选择任务")
                return
            st.markdown(f"### {selected['ticket_no']}")
            st.caption(
                f"{refund_execution_status_label(selected['status'])} · "
                f"已尝试 {selected['attempt_count']} 次"
            )
            st.markdown(f"**执行金额：** {selected['amount']} {selected['currency']}")
            st.markdown(f"**幂等键：** `{selected['idempotency_key']}`")
            st.markdown(f"**失败原因：** {selected.get('failure_message') or '未提供'}")
            if st.button(
                "重试退款",
                icon=":material/refresh:",
                type="primary",
                width="stretch",
            ):
                try:
                    client().retry_refund_execution(selected["ticket_id"])
                    st.rerun()
                except ApiError as error:
                    show_error(error)


def render_config_workspace() -> None:
    with st.container(key="agent-chat"):
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.markdown("### :material/tune: 业务配置")
            if st.button(
                "返回客服会话",
                icon=":material/arrow_back:",
            ):
                st.session_state.agent_view = "待接管"
                st.rerun()
        st.caption("商品、知识分类、售前优惠和售后补偿授权均写入真实数据库并记录审计。")

        product_tab, knowledge_tab, discount_tab, refund_tab, audit_tab = st.tabs(
            ["商品管理", "知识库", "优惠授权", "补偿授权", "审计记录"]
        )

        try:
            products = client().list_products(limit=100)
        except ApiError as error:
            show_error(error)
            products = []

        with product_tab:
            if products:
                selected_product_id = st.selectbox(
                    "选择商品",
                    options=[product["id"] for product in products],
                    format_func=lambda product_id: next(
                        product["name"] for product in products if product["id"] == product_id
                    ),
                    key="config-product-id",
                )
                selected_product = next(
                    product for product in products if product["id"] == selected_product_id
                )
                with st.form("product-update-form"):
                    description = st.text_area(
                        "商品说明",
                        value=selected_product["description"],
                    )
                    specs_text = st.text_area(
                        "结构化参数 JSON",
                        value=json.dumps(
                            selected_product["specs_json"],
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                    price = st.number_input(
                        "价格",
                        min_value=0.0,
                        value=float(selected_product["price"]),
                        step=0.01,
                        format="%.2f",
                    )
                    stock_quantity = st.number_input(
                        "库存",
                        min_value=0,
                        value=int(selected_product["stock_quantity"]),
                        step=1,
                    )
                    is_active = st.checkbox(
                        "上架销售",
                        value=bool(selected_product["is_active"]),
                    )
                    if st.form_submit_button(
                        "保存商品配置",
                        type="primary",
                        width="stretch",
                    ):
                        try:
                            specs_json = json.loads(specs_text)
                            if not isinstance(specs_json, dict):
                                raise ValueError("规格必须是 JSON object")
                            client().update_product(
                                selected_product_id,
                                {
                                    "description": description,
                                    "specs_json": specs_json,
                                    "price": f"{price:.2f}",
                                    "stock_quantity": int(stock_quantity),
                                    "is_active": is_active,
                                },
                            )
                            st.success("商品配置已保存")
                            st.rerun()
                        except (ApiError, ValueError, json.JSONDecodeError) as error:
                            st.error(error.message if isinstance(error, ApiError) else str(error))
            else:
                st.info("当前没有可管理的商品。")

        with knowledge_tab:
            category_labels = {
                "product": "商品知识",
                "business_policy": "业务政策",
                "support_sop": "客服 SOP",
            }
            with st.form("knowledge-upload-form", clear_on_submit=True):
                uploaded_file = st.file_uploader(
                    "上传知识文件",
                    type=["md", "txt", "pdf"],
                )
                category = st.selectbox(
                    "知识分类",
                    options=list(category_labels),
                    format_func=lambda value: category_labels[value],
                )
                product_id = st.selectbox(
                    "关联商品",
                    options=[None] + [product["id"] for product in products],
                    format_func=lambda value: (
                        "不关联商品"
                        if value is None
                        else next(product["name"] for product in products if product["id"] == value)
                    ),
                )
                submitted = st.form_submit_button(
                    "上传并索引",
                    type="primary",
                    width="stretch",
                )
                if submitted:
                    if uploaded_file is None:
                        st.warning("请选择知识文件。")
                    else:
                        try:
                            result = client().upload_knowledge_document(
                                filename=uploaded_file.name,
                                payload=uploaded_file.getvalue(),
                                category=category,
                                product_id=product_id,
                            )
                            st.success(f"文档已处理，Chunk 数：{result['chunk_count']}")
                            st.rerun()
                        except ApiError as error:
                            show_error(error)

            try:
                documents = client().list_knowledge_documents()
            except ApiError as error:
                show_error(error)
                documents = []
            for document in documents:
                with st.expander(
                    f"{document['title']} · "
                    f"{category_labels.get(document['category'], document['category'])}"
                ):
                    st.caption(
                        f"{document['filename']} · {document['status']} · v{document['version']}"
                    )
                    new_category = st.selectbox(
                        "调整分类并重建索引",
                        options=list(category_labels),
                        index=list(category_labels).index(document["category"]),
                        format_func=lambda value: category_labels[value],
                        key=f"knowledge-category-{document['id']}",
                    )
                    left, right = st.columns(2)
                    with left:
                        if st.button(
                            "更新分类",
                            key=f"update-knowledge-{document['id']}",
                            width="stretch",
                        ):
                            try:
                                client().update_knowledge_category(
                                    document["id"],
                                    category=new_category,
                                )
                                st.rerun()
                            except ApiError as error:
                                show_error(error)
                    with right:
                        if st.button(
                            "删除文档",
                            key=f"delete-knowledge-{document['id']}",
                            width="stretch",
                        ):
                            try:
                                client().delete_knowledge_document(document["id"])
                                st.rerun()
                            except ApiError as error:
                                show_error(error)

        with discount_tab:
            try:
                discount_rules = client().list_discount_rules()
            except ApiError as error:
                show_error(error)
                discount_rules = []
            with st.form("discount-rule-create-form"):
                st.markdown("#### 新建优惠授权")
                rule_code = st.text_input(
                    "规则编码",
                    placeholder="例如 headphones_spring",
                )
                display_name = st.text_input("规则名称")
                product_id = st.selectbox(
                    "适用商品",
                    options=[product["id"] for product in products],
                    format_func=lambda value: next(
                        product["name"] for product in products if product["id"] == value
                    ),
                    key="discount-create-product",
                )
                max_rate_percent = st.number_input(
                    "最高折扣比例（%）",
                    min_value=0.01,
                    max_value=100.0,
                    value=5.0,
                    step=0.1,
                )
                max_discount_amount = st.number_input(
                    "最高优惠金额",
                    min_value=0.01,
                    value=50.0,
                    step=1.0,
                )
                if st.form_submit_button(
                    "创建优惠规则",
                    type="primary",
                    width="stretch",
                ):
                    try:
                        client().create_discount_rule(
                            {
                                "rule_code": rule_code,
                                "display_name": display_name,
                                "product_id": product_id,
                                "max_discount_rate": f"{max_rate_percent / 100:.4f}",
                                "max_discount_amount": f"{max_discount_amount:.2f}",
                                "is_active": True,
                            }
                        )
                        st.rerun()
                    except ApiError as error:
                        show_error(error)
            for rule in discount_rules:
                with st.expander(
                    f"{rule['display_name']} · {rule['product_name'] or '未关联商品'}"
                ):
                    with st.form(f"discount-rule-update-{rule['id']}"):
                        name = st.text_input("名称", value=rule["display_name"])
                        rate_percent = st.number_input(
                            "最高折扣比例（%）",
                            min_value=0.01,
                            max_value=100.0,
                            value=float(rule["max_discount_rate"]) * 100,
                            step=0.1,
                        )
                        cap = st.number_input(
                            "最高优惠金额",
                            min_value=0.01,
                            value=float(rule["max_discount_amount"]),
                            step=1.0,
                        )
                        active = st.checkbox("启用", value=bool(rule["is_active"]))
                        if st.form_submit_button("保存", width="stretch"):
                            try:
                                client().update_discount_rule(
                                    rule["id"],
                                    {
                                        "display_name": name,
                                        "max_discount_rate": f"{rate_percent / 100:.4f}",
                                        "max_discount_amount": f"{cap:.2f}",
                                        "is_active": active,
                                    },
                                )
                                st.rerun()
                            except ApiError as error:
                                show_error(error)

        with refund_tab:
            try:
                refund_rules = client().list_refund_authorization_rules()
            except ApiError as error:
                show_error(error)
                refund_rules = []
            with st.form("refund-rule-create-form"):
                st.markdown("#### 新建补偿授权")
                scenario_code = st.text_input(
                    "场景编码",
                    placeholder="例如 packaging_damage",
                )
                display_name = st.text_input("场景名称")
                min_amount = st.number_input(
                    "最低金额",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                )
                max_amount = st.number_input(
                    "最高金额",
                    min_value=0.01,
                    value=50.0,
                    step=1.0,
                )
                if st.form_submit_button(
                    "创建补偿规则",
                    type="primary",
                    width="stretch",
                ):
                    try:
                        client().create_refund_authorization_rule(
                            {
                                "scenario_code": scenario_code,
                                "display_name": display_name,
                                "min_amount": f"{min_amount:.2f}",
                                "max_amount": f"{max_amount:.2f}",
                                "is_active": True,
                            }
                        )
                        st.rerun()
                    except ApiError as error:
                        show_error(error)
            for rule in refund_rules:
                with st.expander(f"{rule['display_name']} · {rule['scenario_code']}"):
                    with st.form(f"refund-rule-update-{rule['id']}"):
                        name = st.text_input("名称", value=rule["display_name"])
                        minimum = st.number_input(
                            "最低金额",
                            min_value=0.0,
                            value=float(rule["min_amount"]),
                            step=1.0,
                        )
                        maximum = st.number_input(
                            "最高金额",
                            min_value=0.01,
                            value=float(rule["max_amount"]),
                            step=1.0,
                        )
                        active = st.checkbox("启用", value=bool(rule["is_active"]))
                        if st.form_submit_button("保存", width="stretch"):
                            try:
                                client().update_refund_authorization_rule(
                                    rule["id"],
                                    {
                                        "display_name": name,
                                        "min_amount": f"{minimum:.2f}",
                                        "max_amount": f"{maximum:.2f}",
                                        "is_active": active,
                                    },
                                )
                                st.rerun()
                            except ApiError as error:
                                show_error(error)

        with audit_tab:
            try:
                audit_logs = client().list_config_audit_logs()
            except ApiError as error:
                show_error(error)
                audit_logs = []
            if not audit_logs:
                st.info("当前没有业务配置变更记录。")
            for log in audit_logs:
                st.markdown(
                    f"**{format_timestamp(log['created_at'])} · "
                    f"{log['entity_type']} #{log['entity_id']} · {log['action']}**"
                )
                st.json(
                    {
                        "before": log.get("before_json"),
                        "after": log.get("after_json"),
                    }
                )


if st.session_state.agent_token is None:
    username, password, submitted = render_login_screen(
        role="客服",
        brand_title="SmartShop AI",
        subtitle="统一处理消费电子产品售后任务、会话上下文与人工回复。",
        account_hint="演示账号：agent_demo / Agent123!",
    )

    if submitted:
        try:
            login = ApiClient().login(username, password)
            if login["user"]["role"] != "agent":
                st.error("请使用客服账号登录", title="角色不匹配")
            else:
                st.session_state.agent_token = login["access_token"]
                st.session_state.agent_user = login["user"]
                st.rerun()
        except ApiError as error:
            show_error(error)
    st.stop()

inject_styles()


@st.fragment(run_every="3s", key="agent_live_workspace")
def render_live_workspace() -> None:
    if st.session_state.agent_switch_to_mine:
        st.session_state.agent_view = "我的会话"
        st.session_state.agent_switch_to_mine = False

    try:
        pending_handoffs = client().list_pending_handoffs()
        my_handoffs = client().list_my_handoffs()
    except ApiError as error:
        show_error(error)
        return

    view = st.session_state.agent_view
    if view == "工单审批":
        render_after_sales_ticket_workspace()
        return
    if view == "退款执行":
        render_refund_execution_workspace()
        return
    if view == "业务配置":
        render_config_workspace()
        return
    handoffs = pending_handoffs if view == "待接管" else my_handoffs
    handoff_by_id = {handoff["id"]: handoff for handoff in handoffs}
    if st.session_state.get("agent_handoff_id") not in handoff_by_id:
        st.session_state.agent_handoff_id = handoffs[0]["id"] if handoffs else None
    selected_handoff_id = st.session_state.get("agent_handoff_id")
    handoff = handoff_by_id.get(selected_handoff_id) if selected_handoff_id is not None else None

    left, center, right = st.columns([0.2, 0.29, 0.51], gap="medium")

    with left:
        with st.container(key="agent-nav"):
            with st.container(key="brand-block"):
                st.markdown("### :material/support_agent: SmartShop AI")
                st.caption("消费电子客服工作台")

            st.markdown("#### 工作队列")
            if st.button(
                f"待接管  {len(pending_handoffs)}",
                icon=":material/pending_actions:",
                type="primary" if view == "待接管" else "secondary",
                width="stretch",
                key="agent-nav-pending",
            ):
                st.session_state.agent_view = "待接管"
                st.rerun()
            if st.button(
                f"我的会话  {len(my_handoffs)}",
                icon=":material/assignment_ind:",
                type="primary" if view == "我的会话" else "secondary",
                width="stretch",
                key="agent-nav-mine",
            ):
                st.session_state.agent_view = "我的会话"
                st.rerun()
            if st.button(
                "工单审批",
                icon=":material/fact_check:",
                width="stretch",
                key="agent-nav-tickets",
            ):
                st.session_state.agent_view = "工单审批"
                st.rerun()
            if st.button(
                "退款执行",
                icon=":material/payments:",
                width="stretch",
                key="agent-nav-refunds",
            ):
                st.session_state.agent_view = "退款执行"
                st.rerun()
            if st.button(
                "业务配置",
                icon=":material/tune:",
                width="stretch",
                key="agent-nav-config",
            ):
                st.session_state.agent_view = "业务配置"
                st.rerun()

            st.caption(":material/sync: 3 秒自动同步")
            st.caption("当前接口提供待接管与已接管会话。")
            st.space("stretch")
            st.caption(f"当前客服：{st.session_state.agent_user['username']}")
            if st.button(
                "退出登录",
                icon=":material/logout:",
                width="stretch",
            ):
                logout()
                st.rerun(scope="app")

    with center:
        with st.container(key="agent-list"):
            st.markdown(f"### {view}")
            st.caption(f"共 {len(handoffs)} 个任务")
            search = st.text_input(
                "搜索会话",
                placeholder="搜索会话编号、原因或来源",
                key="agent_search",
            ).strip()
            filtered = [
                item
                for item in handoffs
                if not search
                or search.lower()
                in f"{item['session_id']} {item['reason']} {item['source']}".lower()
            ]

            if not filtered:
                st.info(
                    "没有符合搜索条件的会话。" if search else "当前队列为空。",
                    title="暂无任务",
                )
            else:
                with st.container(key="handoff-list", height=620):
                    for item in filtered:
                        item_id = item["id"]
                        is_selected = item_id == selected_handoff_id
                        with st.container(key=f"agent-handoff-{item_id}"):
                            if st.button(
                                f"会话 #{item['session_id']}",
                                key=f"select-handoff-{item_id}",
                                type="primary" if is_selected else "secondary",
                                width="stretch",
                            ):
                                st.session_state.agent_handoff_id = item_id
                                st.rerun()
                            st.caption(" ".join(item["reason"].split())[:48])
                            st.caption(
                                f"{handoff_status_label(item['status'])} · "
                                f"{format_timestamp(item['created_at'])}"
                            )

    with right:
        with st.container(key="agent-chat"):
            if handoff is None:
                st.info("从中间列表选择一个会话。", title="尚未选择会话")
                return

            if view == "待接管":
                with st.container(key="detail-card"):
                    st.markdown(f"### :material/pending_actions: 会话 #{handoff['session_id']}")
                    st.markdown(f"**转人工原因**  \n{handoff['reason']}")
                    st.caption(
                        f"来源：{SOURCE_LABELS.get(handoff['source'], handoff['source'])}"
                        f" · {format_timestamp(handoff['created_at'])}"
                    )
                    st.caption("接管后可查看完整对话、订单摘要并进行人工回复。")
                    if st.button(
                        "接管此会话",
                        icon=":material/assignment_ind:",
                        type="primary",
                        width="stretch",
                    ):
                        try:
                            client().claim_handoff(handoff["id"])
                            st.session_state.agent_switch_to_mine = True
                            st.rerun()
                        except ApiError as error:
                            show_error(error)
                return

            try:
                context = client().get_agent_session(handoff["session_id"])
            except ApiError as error:
                show_error(error)
                return

            chat_session = context["session"]
            with st.container(horizontal=True, horizontal_alignment="distribute"):
                st.markdown(f"### :material/forum: 会话 #{chat_session['id']}")
                st.markdown(f":green-badge[{status_label(chat_session['status'])}]")
            workflow = (
                "人工处理中"
                if chat_session["status"] == "human_active"
                else workflow_label(chat_session["workflow_state"])
            )
            st.caption(f"会话编号 #{chat_session['id']} · {workflow}")

            message_column, detail_column = st.columns([0.69, 0.31], gap="medium")
            with message_column:
                with st.container(key="message-scroll", height=500):
                    for message in context["messages"]:
                        render_message(message, staff_view=True)

                if chat_session["status"] != "closed":
                    with st.form("agent_reply_form", clear_on_submit=True):
                        reply = st.text_area(
                            "人工回复",
                            max_chars=4000,
                            height=110,
                            placeholder="输入回复内容",
                            key="agent_reply_text",
                        )
                        submitted = st.form_submit_button(
                            "发送回复",
                            icon=":material/send:",
                            type="primary",
                            width="stretch",
                        )
                    if submitted:
                        if not reply.strip():
                            st.warning("回复内容不能为空。")
                        else:
                            with st.spinner("正在发送人工回复..."):
                                try:
                                    client().reply_as_agent(
                                        handoff["session_id"],
                                        reply.strip(),
                                    )
                                    st.rerun()
                                except ApiError as error:
                                    show_error(error)
                else:
                    st.success("会话已关闭。", icon=":material/task_alt:")

            with detail_column:
                render_order_card(context.get("order"))
                st.space("medium")
                render_session_meta(chat_session)
                st.space("medium")
                st.markdown("#### 人工任务")
                st.caption(f"任务状态：{handoff_status_label(context['handoff']['status'])}")
                handoff_source = context["handoff"]["source"]
                st.caption(f"转人工来源：{SOURCE_LABELS.get(handoff_source, handoff_source)}")
                if chat_session["status"] != "closed":
                    if st.button(
                        "结束会话",
                        icon=":material/task_alt:",
                        width="stretch",
                    ):
                        try:
                            client().close_agent_session(handoff["session_id"])
                            st.rerun()
                        except ApiError as error:
                            show_error(error)


render_live_workspace()
