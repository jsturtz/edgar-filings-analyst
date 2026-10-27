import os

from edgar_agent import config
from edgar_agent.llm import structured_output_method


def _with_env(**env):
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items()})
    return saved


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_default_provider_is_anthropic():
    saved = _with_env(LLM_PROVIDER="anthropic", ANTHROPIC_MODEL="claude-test")
    try:
        s = config.get_settings()
        assert (s.provider, s.model) == ("anthropic", "claude-test")
        assert structured_output_method() == "json_schema"
    finally:
        _restore(saved)


def test_azure_uses_deployment_name():
    saved = _with_env(LLM_PROVIDER="Azure_OpenAI", AZURE_OPENAI_DEPLOYMENT="gpt-4.1-mini")
    try:
        s = config.get_settings()
        assert (s.provider, s.model) == ("azure_openai", "gpt-4.1-mini")
        assert structured_output_method() == "function_calling"
    finally:
        _restore(saved)
