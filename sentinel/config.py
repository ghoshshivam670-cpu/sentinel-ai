import os
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_core.language_models.chat_models import BaseChatModel

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    default_llm_provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    model_name: Optional[str] = None

    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Langfuse Observability
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Execution Bounds
    max_self_healing_iterations: int = Field(default=3, ge=1, le=10)
    execution_timeout_seconds: int = Field(default=15, ge=2, le=60)
    enable_human_in_the_loop: bool = False

settings = Settings()

def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Factory function providing a unified interface across top LLM providers.
    Automatically initializes according to active configuration in .env.
    """
    provider = settings.default_llm_provider.lower()
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = settings.gemini_api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        model = settings.model_name or "gemini-3.5-flash-lite"
        primary_llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=api_key,
            max_retries=3,
        )
        fallback_model_name = "gemini-3.8-flash" if model != "gemini-3.8-flash" else "gemini-3.5-flash-lite"
        fallback_llm = ChatGoogleGenerativeAI(
            model=fallback_model_name,
            temperature=temperature,
            google_api_key=api_key,
            max_retries=3,
        )
        return primary_llm.with_fallbacks([fallback_llm])
        
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        model = settings.model_name or "gpt-4o"
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key
        )
        
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        model = settings.model_name or "claude-3-5-sonnet-20241022"
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            api_key=api_key
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
