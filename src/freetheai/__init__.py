"""Official Python client for the FreeTheAI API (https://freetheai.org).

One OpenAI-compatible endpoint with free AI models, web search, and media
tasks. Docs: https://freetheai.org/docs
"""

from ._client import DEFAULT_BASE_URL, AsyncFreeTheAI, FreeTheAI
from ._errors import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    CheckinRequiredError,
    ConcurrencyLimitError,
    ContentFilterError,
    DailyLimitError,
    EmailNotVerifiedError,
    FreeTheAIError,
    ImagesNotSupportedError,
    IncompleteKeyError,
    InternalServerError,
    ModelBusyError,
    ModelNotFoundError,
    NotFoundError,
    PermissionDeniedError,
    ProviderBudgetError,
    RateLimitError,
    RequestTooLargeError,
    StreamInterruptedError,
    TaskFailedError,
)
from ._version import __version__

__all__ = [
    "DEFAULT_BASE_URL",
    "APIConnectionError",
    "APIStatusError",
    "AsyncFreeTheAI",
    "AuthenticationError",
    "BadRequestError",
    "CheckinRequiredError",
    "ConcurrencyLimitError",
    "ContentFilterError",
    "DailyLimitError",
    "EmailNotVerifiedError",
    "FreeTheAI",
    "FreeTheAIError",
    "ImagesNotSupportedError",
    "IncompleteKeyError",
    "InternalServerError",
    "ModelBusyError",
    "ModelNotFoundError",
    "NotFoundError",
    "PermissionDeniedError",
    "ProviderBudgetError",
    "RateLimitError",
    "RequestTooLargeError",
    "StreamInterruptedError",
    "TaskFailedError",
    "__version__",
]
