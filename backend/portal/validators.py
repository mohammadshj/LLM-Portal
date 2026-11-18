"""Validate operator-managed endpoints and credential references."""

from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator

validate_key_env = RegexValidator(
    regex=r"\ALLM_(?:[A-Z0-9]+_)*API_KEY\Z",
    message="نام متغیر باید مانند LLM_API_KEY یا LLM_SERVICE_API_KEY باشد؛ خود کلید را وارد نکنید.",
)


def validate_connection_url(value):
    URLValidator(schemes=["http", "https"])(value)
    parts = urlsplit(value)
    if (
        parts.username is not None
        or parts.password is not None
        or "?" in value
        or "#" in value
    ):
        raise ValidationError(
            "آدرس API نباید شامل نام کاربری، رمز، query یا fragment باشد."
        )
