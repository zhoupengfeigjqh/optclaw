from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    """Config section for a model"""

    # 唯一标识名称
    name: str = Field(..., description="Unique name for the model")
    # 模型官方名称
    model: str = Field(..., description="Model name")
    # API 基础地址
    base_url: str = Field(..., description="Base URL for the model API")
    # API 密钥
    api_key: str = Field(..., description="API key for authentication")
    # 模型提供者类路径  补丁修正
    use: str = Field(
        ...,
        description="Class path of the model provider(e.g. langchain_openai.ChatOpenAI)",
    )

    # 可选描述信息
    description: str | None = Field(
        default=None,
        description="Description for the model"
    )
    # 请求超时时间（秒）
    timeout: float = Field(
        default=60.0,
        description="Request timeout in seconds"
    )
    # 最大重试次数
    max_retries: int = Field(
        default=2,
        description="Maximum number of retries for failed requests"
    )
    # 是否支持思考过程
    supports_thinking: bool = Field(
        default=False,
        description="Whether the model supports thinking/chain-of-thought"
    )
    # 是否支持视觉能力
    supports_vision: bool = Field(
        default=False,
        description="Whether the model supports vision/image inputs"
    )
    # 是否支持推理强度配置
    supports_reasoning_effort: bool = Field(
        default=False,
        description="Whether the model supports reasoning effort adjustment"
    )

    # 当思考过程启用时，传递给模型的额外设置
    thinking: dict | None = Field(
        default_factory=lambda: None,
        description=(
            "Thinking settings for the model. If provided, these settings will be passed to the model when thinking is enabled. "
            "This is a shortcut for `when_thinking_enabled` and will be merged with `when_thinking_enabled` if both are provided."
        ),
    )

    # 当思考过程启用时，传递给模型的额外设置（更灵活，可以针对不同的思考阶段配置不同的设置）
    when_thinking_enabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is enabled",
    )

    # 允许额外字段
    model_config = ConfigDict(extra="allow")