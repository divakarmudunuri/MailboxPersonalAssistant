"""Provider-switchable chat models: every agent picks its own (provider, model) pair from the config."""

from functools import cache

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from mail_assistant.config.__app_config__ import (
    ANTHROPIC_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_CTX,
    OPENAI_API_KEY,
    TRIAGE_LLM,
)


def _ollama(model: str) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(model=model, base_url=OLLAMA_BASE_URL, temperature=0, num_ctx=OLLAMA_NUM_CTX)


def _require(key: str, name: str) -> str:
    """Fail early with a clear message instead of a 401 from the provider."""
    if not key:
        raise ValueError(f"{name} is not set; add it to .env (see .env.example)")
    return key


def _anthropic(model: str) -> BaseChatModel:
    # Current Claude models reject sampling params, so none are set.
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, api_key=_require(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"))


def _openai(model: str) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, api_key=_require(OPENAI_API_KEY, "OPENAI_API_KEY"))


_PROVIDERS = {"ollama": _ollama, "anthropic": _anthropic, "openai": _openai}


@cache
def chat_model(provider: str, model: str) -> BaseChatModel:
    """The chat model for a provider and model name, built once per pair."""
    try:
        return _PROVIDERS[provider](model)
    except KeyError:
        raise ValueError(f"LLM provider must be one of {sorted(_PROVIDERS)}, not {provider!r}") from None


@cache
def structured_model(schema: type[BaseModel], provider: str, model: str) -> Runnable:
    """The chat model constrained to return an instance of `schema`, built once per schema and model."""
    return chat_model(provider, model).with_structured_output(schema)


def ask(
    schema: type[BaseModel],
    system_prompt: str,
    user_text: str,
    run_name: str = "ask",
    llm: tuple[str, str] = TRIAGE_LLM,
) -> BaseModel:
    """Send one system + user turn and return the model's answer parsed as `schema`; `run_name` labels the trace,
    `llm` is the agent's (provider, model) pair."""
    messages = [("system", system_prompt), ("user", user_text)]
    return structured_model(schema, *llm).invoke(messages, config={"run_name": run_name})
