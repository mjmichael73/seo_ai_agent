"""Optional OpenAI-compatible LangChain model configuration."""

from langchain_openai import ChatOpenAI

from seo_ai_agent.config import Settings


def build_llm(settings: Settings) -> ChatOpenAI | None:
    """Create the optional synthesis model, or remain fully usable without credentials."""

    if not settings.llm_enabled:
        return None
    api_key = settings.openai_api_key.get_secret_value()  # type: ignore[union-attr]
    options: dict[str, object] = {
        "model": settings.openai_model,
        "api_key": api_key,
        "temperature": 0,
    }
    if settings.openai_base_url:
        options["base_url"] = settings.openai_base_url
    return ChatOpenAI(**options)
