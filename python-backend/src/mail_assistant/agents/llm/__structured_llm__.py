"""Provider-switchable chat models: LLM_PROVIDER picks the triage model; agents may ask for another one."""

from functools import cache

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from mail_assistant.config.__app_config__ import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OPENAI_API_KEY,
    OPENAI_MODEL,
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
_DEFAULT_MODELS = {"ollama": OLLAMA_MODEL, "anthropic": ANTHROPIC_MODEL, "openai": OPENAI_MODEL}


@cache
def chat_model(provider: str = LLM_PROVIDER, model: str | None = None) -> BaseChatModel:
    """The chat model for a provider (LLM_PROVIDER by default) and model name (that provider's default), built once."""
    try:
        return _PROVIDERS[provider](model or _DEFAULT_MODELS[provider])
    except KeyError:
        raise ValueError(f"LLM provider must be one of {sorted(_PROVIDERS)}, not {provider!r}") from None


@cache
def structured_model(schema: type[BaseModel]) -> Runnable:
    """The chat model constrained to return an instance of `schema`, built once per schema."""
    return chat_model().with_structured_output(schema)


def ask(schema: type[BaseModel], system_prompt: str, user_text: str) -> BaseModel:
    """Send one system + user turn and return the model's answer parsed as `schema`."""
    return structured_model(schema).invoke([("system", system_prompt), ("user", user_text)])
