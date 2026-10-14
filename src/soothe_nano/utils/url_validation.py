"""URL validation and sanitization utilities."""

from soothe_nano._rust_compat import validate_url_rust


def validate_url(url: str) -> tuple[str, str | None]:
    """Validate and sanitize URL.

    Returns:
        Tuple of (sanitized_url, error_message)
        If error_message is not None, the URL is invalid.
    """
    return validate_url_rust(url)
