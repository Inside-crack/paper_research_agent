from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..logging import get_logger
from .base import BaseLLM
from .openai_llm import OpenAILLM

logger = get_logger(__name__)

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "eval_model": "gpt-4o",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "eval_model": "deepseek-v4-pro",
    },
    "deepseek-v4-flash": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    "deepseek-v4-pro": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    },
}


class LLMFactory:
    _providers: dict[str, type[BaseLLM]] = {
        "openai": OpenAILLM,
        "deepseek": OpenAILLM,
        "deepseek-v4-flash": OpenAILLM,
        "deepseek-v4-pro": OpenAILLM,
    }

    @classmethod
    def register(cls, name: str, provider_class: type[BaseLLM]) -> None:
        cls._providers[name] = provider_class

    @classmethod
    def create(
        cls,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> BaseLLM:
        settings = get_settings()
        provider = provider or settings.llm.provider

        provider_defaults = PROVIDER_DEFAULTS.get(provider, {})
        provider_class = cls._providers.get(provider)
        if not provider_class:
            raise ValueError(
                f"Unknown LLM provider: {provider}. Available: {list(cls._providers.keys())}"
            )

        api_key = kwargs.pop("api_key", None) or settings.llm.api_key
        if not api_key:
            env_key_name = f"{provider.upper().replace('-', '_')}_API_KEY"
            import os
            api_key = os.environ.get(env_key_name, "") or os.environ.get("DEEPSEEK_API_KEY", "")

        base_url = kwargs.pop("base_url", None) or settings.llm.base_url or provider_defaults.get("base_url")
        model = model or settings.llm.model or provider_defaults.get("model")
        temperature = temperature if temperature is not None else settings.llm.temperature

        if not api_key:
            logger.warning(f"No API key configured for provider {provider}. Set DEEPSEEK_API_KEY in .env")

        return provider_class(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=kwargs.pop("max_tokens", settings.llm.max_tokens),
            timeout=kwargs.pop("timeout", settings.llm.timeout),
            **kwargs,
        )


def create_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    **kwargs: Any,
) -> BaseLLM:
    return LLMFactory.create(provider=provider, model=model, temperature=temperature, **kwargs)


def create_eval_llm(**kwargs: Any) -> BaseLLM:
    settings = get_settings()
    provider = kwargs.pop("provider", settings.llm.provider)
    provider_defaults = PROVIDER_DEFAULTS.get(provider, {})
    eval_model = settings.llm.eval_model or provider_defaults.get("eval_model") or settings.llm.model
    return create_llm(provider=provider, model=eval_model, temperature=0.0, **kwargs)
