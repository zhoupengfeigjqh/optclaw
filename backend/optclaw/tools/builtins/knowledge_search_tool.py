"""Knowledge search tool — hybrid retrieval (keyword + vector) from the knowledge base."""

from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime

from optclaw.log import setup_logging

logger = setup_logging(__name__)

_MAX_CONTENT_LENGTH = 1500


def _fmt_content(content: str) -> str:
    if len(content) > _MAX_CONTENT_LENGTH:
        return content[:_MAX_CONTENT_LENGTH] + "..."
    return content


@tool("knowledge_search", parse_docstring=True)
async def knowledge_search_tool(query: str, runtime: ToolRuntime) -> str:
    """使用混合检索（关键词 + 向量搜索）查询知识库，从已索引文档中查找最相关的内容片段，含图片信息。

    适用场景：
    - 从用户上传的知识库文档中检索信息
    - 用户询问可能存在于已索引文件中的内容
    - 需要从已存储文档中获取精确、有来源的答案

    不适用：浏览实时网页（用 web_search）、直接读磁盘文件（用 read_file）

    Args:
        query: 搜索查询文本，在知识库中查找相关内容。
    """

    score_threshold = 0.5
    use_rerank = True
    top_k = 5
    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None

    # align with the knowledge base
    if agent_name is None:
        agent_name = "default"

    logger.warning(f"Executing knowledge search with query: \"{query}\", agent_name: {agent_name}, top_k: {top_k}, score_threshold: {score_threshold}, use_rerank: {use_rerank}")

    try:
        from knowledge.retriever import hybrid_search
    except ImportError as e:
        logger.error(f"Failed to import knowledge module: {e}")
        return f"Error: Knowledge base module is not available. Please check that the knowledge service is properly configured."

    try:
        results = await hybrid_search(
            query=query,
            top_k=min(top_k, 10),
            threshold=score_threshold,
            use_rerank=use_rerank,
            agent_name=agent_name,
        )
    except Exception as e:
        logger.error(f"Knowledge hybrid search failed: {e}")
        return f"Error: Knowledge search failed — {e}"

    if not results:
        return f"No relevant content found in the knowledge base for query: \"{query}\"."

    lines = [f"Found {len(results)} result(s) for \"{query}\":\n"]
    for i, r in enumerate(results, 1):
        file_name = r.get("file_name", "unknown")
        score = r.get("score", 0.0)
        source = r.get("source_type", "unknown")
        content = _fmt_content(r.get("content", ""))
        lines.append(
            f"--- Result {i} (score: {score:.3f}, source: {source}, file: {file_name}) ---\n"
            f"{content}\n"
        )

    logger.info(f"Formatted search results:\n{lines}")

    return "\n".join(lines)
