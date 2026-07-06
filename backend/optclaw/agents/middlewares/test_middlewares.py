"""Tests for middlewares module."""

import pytest
from unittest.mock import patch, MagicMock


class TestCreateSummarizationMiddleware:
    """Test suite for _create_summarization_middleware function."""

    # ============================================================
    # Test Cases for Enabled/Disabled Configuration
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_returns_none_when_disabled(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test that None is returned when summarization is disabled."""
        from optclaw.config.summarization_config import SummarizationConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(enabled=False)

        result = _create_summarization_middleware()

        assert result is None
        mock_create_model.assert_not_called()

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_returns_middleware_when_enabled(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test that middleware instance is returned when summarization is enabled."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware
        from optclaw.agents.middlewares.summarization_middleware import OptClawSummarizationMiddleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert isinstance(result, OptClawSummarizationMiddleware)

    # ============================================================
    # Test Cases for Trigger Parameter
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_trigger_single_context_size(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test trigger with single ContextSize object."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            trigger=ContextSize(type="messages", value=50),
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        # Check trigger was converted to tuple format
        assert result.trigger == ("messages", 50)

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_trigger_list_of_context_size(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test trigger with list of ContextSize objects."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            trigger=[
                ContextSize(type="messages", value=50),
                ContextSize(type="tokens", value=4000)
            ],
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        # Check trigger was converted to list of tuples
        assert result.trigger == [("messages", 50), ("tokens", 4000)]

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_trigger_none(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test trigger when set to None."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            trigger=None,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert result.trigger is None

    # ============================================================
    # Test Cases for Keep Parameter
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_keep_parameter_with_tokens(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test keep parameter with tokens type."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            keep=ContextSize(type="tokens", value=3000)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert result.keep == ("tokens", 3000)

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_keep_parameter_with_fraction(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test keep parameter with fraction type."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            keep=ContextSize(type="fraction", value=0.3)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert result.keep == ("fraction", 0.3)

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_keep_default_value(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test keep parameter uses default value when not specified."""
        from optclaw.config.summarization_config import SummarizationConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(enabled=True)
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        # Default is ContextSize(type="messages", value=20)
        assert result.keep == ("messages", 20)

    # ============================================================
    # Test Cases for Model Configuration
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_model_with_explicit_name(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test model creation with explicit model_name."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            model_name="gpt-4",
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        mock_create_model.assert_called_once_with(name="gpt-4", thinking_enabled=False)
        assert result is not None

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_model_without_name_uses_default(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test model creation falls back to default when model_name is None."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            model_name=None,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        mock_create_model.assert_called_once_with(thinking_enabled=False)
        assert result is not None

    # ============================================================
    # Test Cases for Optional Parameters
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_trim_tokens_to_summarize(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test trim_tokens_to_summarize parameter is passed."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            trim_tokens_to_summarize=6000,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert result.trim_tokens_to_summarize == 6000

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_trim_tokens_to_summarize_none(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test trim_tokens_to_summarize when set to None."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            trim_tokens_to_summarize=None,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        # When None, parameter should not be passed to middleware
        assert not hasattr(result, "trim_tokens_to_summarize") or result.trim_tokens_to_summarize is None

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_summary_prompt(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test summary_prompt parameter is passed."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        custom_prompt = "Please summarize the conversation focusing on key decisions."
        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            summary_prompt=custom_prompt,
            keep=ContextSize(type="messages", value=20)
        )
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert result.summary_prompt == custom_prompt

    # ============================================================
    # Test Cases for Before Summarization Hooks
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_memory_flush_hook_added_when_memory_enabled(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test memory_flush_hook is added when memory is enabled."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.config.memory_config import MemoryConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware
        from optclaw.agents.memory.summarization_hook import memory_flush_hook

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            keep=ContextSize(type="messages", value=20)
        )
        mock_get_memory_config.return_value = MemoryConfig(enabled=True)
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert memory_flush_hook in result._before_summarization_hooks

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_no_hooks_when_memory_disabled(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test no hooks are added when memory is disabled."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.config.memory_config import MemoryConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            keep=ContextSize(type="messages", value=20)
        )
        mock_get_memory_config.return_value = MemoryConfig(enabled=False)
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        assert len(result._before_summarization_hooks) == 0

    # ============================================================
    # Test Cases for Edge Cases
    # ============================================================

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_all_optional_params_none(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test middleware creation when all optional params are None."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.config.memory_config import MemoryConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            model_name=None,
            trigger=None,
            trim_tokens_to_summarize=None,
            summary_prompt=None,
            keep=ContextSize(type="messages", value=20)
        )
        mock_get_memory_config.return_value = MemoryConfig(enabled=False)
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        mock_create_model.assert_called_once_with(thinking_enabled=False)

    @patch("optclaw.agents.middlewares.middlewares.get_memory_config")
    @patch("optclaw.agents.middlewares.middlewares.create_chat_model")
    @patch("optclaw.agents.middlewares.middlewares.get_summarization_config")
    def test_complete_configuration(
        self, mock_get_config, mock_create_model, mock_get_memory_config
    ):
        """Test middleware with complete configuration."""
        from optclaw.config.summarization_config import SummarizationConfig, ContextSize
        from optclaw.config.memory_config import MemoryConfig
        from optclaw.agents.middlewares.middlewares import _create_summarization_middleware

        mock_get_config.return_value = SummarizationConfig(
            enabled=True,
            model_name="claude-3",
            trigger=[
                ContextSize(type="messages", value=100),
                ContextSize(type="tokens", value=8000),
            ],
            keep=ContextSize(type="fraction", value=0.25),
            trim_tokens_to_summarize=5000,
            summary_prompt="Custom summary: {messages}"
        )
        mock_get_memory_config.return_value = MemoryConfig(enabled=True)
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        result = _create_summarization_middleware()

        assert result is not None
        mock_create_model.assert_called_once_with(name="claude-3", thinking_enabled=False)
        assert result.trigger == [("messages", 100), ("tokens", 8000)]
        assert result.keep == ("fraction", 0.25)
        assert result.trim_tokens_to_summarize == 5000
        assert result.summary_prompt == "Custom summary: {messages}"
