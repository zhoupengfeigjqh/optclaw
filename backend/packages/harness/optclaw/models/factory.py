import logging
from langchain_core.language_models import BaseChatModel

from optclaw.config import get_app_config


logger = logging.getLogger(__name__)


def _deep_merge_dicts(base: dict | None, override: dict) -> dict:
    """Recursively merge two dictionaries without mutating the inputs."""
    merged = dict(base or {})
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _vllm_disable_chat_template_kwargs(chat_template_kwargs: dict) -> dict:
    """Build the disable payload for vLLM/Qwen chat template kwargs."""
    disable_kwargs: dict[str, bool] = {}
    if "thinking" in chat_template_kwargs:
        disable_kwargs["thinking"] = False
    if "enable_thinking" in chat_template_kwargs:
        disable_kwargs["enable_thinking"] = False
    return disable_kwargs


def create_chat_model(name: str | None = None, thinking_enabled: bool = False, **kwargs) -> BaseChatModel:
    """Create a chat model instance from the config.

    Args:
        name: The name of the model to create. If None, the first model in the config will be used.

    Returns:
        A chat model instance.
    """
    config = get_app_config()
    if name is None:
        name = config.models[0].name
    model_config = config.get_model_config(name)
    if model_config is None:
        raise ValueError(f"Model {name} not found in config") from None
    
    model_settings_from_config = model_config.model_dump(
    exclude_none=True,
    exclude={
        "use",
        "name",
        "display_name",
        "description",
        "supports_thinking",
        "supports_reasoning_effort",
        "when_thinking_enabled",
        "thinking",
        "supports_vision",
    },
    )

    # Compute effective when_thinking_enabled by merging in the `thinking` shortcut field.
    # The `thinking` shortcut is equivalent to setting when_thinking_enabled["thinking"].
    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}
    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(f"Model {name} does not support thinking. Set `supports_thinking` to true in the `config.yaml` to enable thinking.") from None
        if effective_wte:
            model_settings_from_config.update(effective_wte)
    if not thinking_enabled and has_thinking_settings:
        if effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"thinking": {"type": "disabled"}},
            )
            model_settings_from_config["reasoning_effort"] = "minimal"
        elif disable_chat_template_kwargs := _vllm_disable_chat_template_kwargs(effective_wte.get("extra_body", {}).get("chat_template_kwargs") or {}):
            # vLLM uses chat template kwargs to switch thinking on/off.
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"chat_template_kwargs": disable_chat_template_kwargs},
            )
        elif effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            model_settings_from_config["thinking"] = {"type": "disabled"}
    if not model_config.supports_reasoning_effort:
        kwargs.pop("reasoning_effort", None)
        model_settings_from_config.pop("reasoning_effort", None)

    logger.warning(f"Creating model '{name}' with settings: {model_settings_from_config} and kwargs: {kwargs}")
    
    # model type
    logger.warning(f"Model class: {model_config.use}")
    model_class_name = model_config.use.split(':')[1]
    if model_class_name is None:
        # 允许在 config.yaml 中指定一个完全自定义的模型类，覆盖默认的 ChatOpenAI
        raise Exception(f'模型类型设置{model_config.use}缺失，请检查！')
    if model_class_name == 'PatchedChatDeepSeek':
        from optclaw.models.patched_deepseek import PatchedChatDeepSeek
        model_class = PatchedChatDeepSeek
    elif model_class_name == 'PatchedChatMiniMax':
        from optclaw.models.patched_minimax import PatchedChatMiniMax
        model_class = PatchedChatMiniMax
    elif model_class_name == 'PatchedChatOpenAI':
        from optclaw.models.patched_openai import PatchedChatOpenAI
        model_class = PatchedChatOpenAI
    elif model_class_name == 'ChatOpenAI':
        from langchain_openai import ChatOpenAI
        model_class = ChatOpenAI
    else:
        raise Exception(f'不支持的模型类型：{model_class_name}，请检查！')

    model:BaseChatModel = model_class(**model_settings_from_config)

    return model
