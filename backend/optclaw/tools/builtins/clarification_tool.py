from typing import Literal

from langchain.tools import tool


@tool("ask_clarification", parse_docstring=True, return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal[
        "missing_info",
        "ambiguous_requirement",
        "approach_choice",
        "risk_confirmation",
        "suggestion",
    ],
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """当需要更多信息才能继续时，向用户发起澄清询问。

    遇到以下情况且无法继续时调用此工具：

    - **信息缺失**：必要细节未提供（如文件路径、URL、具体需求）
    - **需求歧义**：存在多种合理解读
    - **方案选择**：有多种可行方案，需用户指定偏好
    - **风险确认**：破坏性操作需明确确认（如删文件、修改生产环境）
    - **建议审批**：有推荐方案但需用户同意

    调用后执行中断，问题呈现给用户。等待用户回复后再继续。

    最佳实践：
    - 一次只问一个澄清问题
    - 问题要具体明确
    - 需要澄清时不要自行假设
    - 高风险操作必须确认
    - 调用后执行自动中断

    Args:
        question: 向用户提出的澄清问题，需具体明确。
        clarification_type: 澄清类型（missing_info, ambiguous_requirement, approach_choice, risk_confirmation, suggestion）。
        context: 可选，说明为何需要澄清，帮助用户理解。
        options: 可选选项列表（用于 approach_choice 或 suggestion 类型）。
    """
    # This is a placeholder implementation
    # The actual logic is handled by ClarificationMiddleware which intercepts this tool call
    # and interrupts execution to present the question to the user
    return "Clarification request processed by middleware"
