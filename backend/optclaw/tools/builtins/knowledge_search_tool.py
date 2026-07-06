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
    """Search the knowledge base using hybrid retrieval (keyword + vector search combined).
    This tool queries indexed documents to find the most relevant content chunks, including the image information.

    When to use the knowledge_search tool:
    - When you need to retrieve information from the user's uploaded knowledge base documents
    - When the user asks about content that may exist in indexed files
    - When you need precise, sourced answers from stored documents

    When NOT to use:
    - For browsing the live web (use web_search instead)
    - For reading files directly from disk (use read_file instead)

    Args:
        query: The search query text (keywords separated by spaces) to find relevant content in the knowledge base.
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
