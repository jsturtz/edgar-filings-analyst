"""Chat model factory, so the same graph runs on Anthropic or Azure OpenAI.

Pick the provider with LLM_PROVIDER in .env:
  anthropic     (default)  ANTHROPIC_API_KEY, ANTHROPIC_MODEL
  azure_openai             AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
                           AZURE_OPENAI_DEPLOYMENT, OPENAI_API_VERSION
"""

from __future__ import annotations

from .config import get_settings

PROVIDERS = ("anthropic", "azure_openai")


def chat_model(model: str | None = None, max_tokens: int = 2048):
    """`model` is a model id for Anthropic, or a deployment name for Azure OpenAI."""
    settings = get_settings()
    if settings.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Newer Claude models reject non-default temperature, so sampling stays at the default.
        return ChatAnthropic(model=model or settings.model, max_tokens=max_tokens)
    if settings.provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        # Endpoint, key and API version are read from AZURE_OPENAI_ENDPOINT,
        # AZURE_OPENAI_API_KEY and OPENAI_API_VERSION.
        return AzureChatOpenAI(azure_deployment=model or settings.model, max_tokens=max_tokens)
    raise ValueError(f"LLM_PROVIDER must be one of {PROVIDERS}, got {settings.provider!r}")


def structured_output_method() -> str:
    """Claude Sonnet 5.5 needs native JSON-schema output; tool calling is the most
    portable choice across Azure OpenAI deployments."""
    return "json_schema" if get_settings().provider == "anthropic" else "function_calling"
