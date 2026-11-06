import os
from typing import Optional
from sentinel.config import settings

def get_langfuse_callback_handler():
    """
    Returns a configured Langfuse CallbackHandler if credentials are provided in settings.
    Gracefully falls back to None if unconfigured.
    """
    public_key = settings.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = settings.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        return None

    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=settings.langfuse_host
        )
    except ImportError:
        return None
