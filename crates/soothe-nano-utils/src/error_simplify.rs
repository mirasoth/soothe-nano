//! Error simplification and classification.
//!
//! Pure string-pattern logic for converting exceptions into user-friendly
//! messages and classifying them as warning-level vs error-level.

/// HTTP status codes for warning-level errors.
pub const HTTP_FORBIDDEN: i32 = 403;
pub const HTTP_TOO_MANY_REQUESTS: i32 = 429;

/// Structural tokens per message.
pub const STRUCTURAL_TOKENS_PER_MESSAGE: i64 = 3;

/// Check if a TypeError message is about an unexpected keyword argument.
pub fn is_unexpected_keyword_error(error_msg: &str) -> bool {
    error_msg.contains("unexpected keyword argument")
}

/// Extract the unexpected keyword name from a TypeError message.
///
/// Looks for `got an unexpected keyword argument 'name'` or `"name"`.
/// Returns `None` if no match is found.
pub fn unexpected_kwarg_name(error_msg: &str) -> Option<String> {
    // Find the pattern: `unexpected keyword argument ' or "
    let marker = "unexpected keyword argument ";
    let idx = error_msg.find(marker)?;
    let rest = &error_msg[idx + marker.len()..];
    if rest.is_empty() {
        return None;
    }
    let quote = rest.chars().next()?;
    if quote == '\'' || quote == '"' {
        // Find the matching closing quote.
        let inner = &rest[1..];
        let end = inner.find(quote)?;
        Some(inner[..end].to_string())
    } else {
        None
    }
}

/// Check if a TypeError message is about a missing required positional argument.
pub fn is_missing_required_argument(error_msg: &str) -> bool {
    error_msg.contains("required positional argument")
        || error_msg.contains("required keyword-only argument")
}

/// Extract the count from a "missing N required positional argument" message.
pub fn missing_required_count(error_msg: &str) -> Option<String> {
    // Pattern: "missing {N} required positional argument"
    let marker = "missing ";
    let idx = error_msg.find(marker)?;
    let rest = &error_msg[idx + marker.len()..];
    // Take leading digits.
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return None;
    }
    // Verify it's followed by " required"
    let after_digits = &rest[digits.len()..];
    if after_digits.starts_with(" required") {
        Some(digits)
    } else {
        None
    }
}

/// Check if a TypeError is a recoverable LLM tool-argument error.
pub fn is_llm_argument_error(error_type: &str, error_msg: &str) -> bool {
    if error_type != "TypeError" {
        return false;
    }
    error_msg.contains("unexpected keyword argument")
        || error_msg.contains("required positional argument")
        || error_msg.contains("required keyword-only argument")
}

/// Check if an error should be logged as warning (non-critical/recoverable).
///
/// `status` is the HTTP status from `exc.status` or `exc.response.status`.
/// Returns `true` for LLM argument errors, 403, and 429.
pub fn is_warning_level_error(error_type: &str, error_msg: &str, status: Option<i32>) -> bool {
    if is_llm_argument_error(error_type, error_msg) {
        return true;
    }
    if let Some(s) = status {
        if s == HTTP_FORBIDDEN || s == HTTP_TOO_MANY_REQUESTS {
            return true;
        }
    }
    false
}

/// Convert an error into a user-friendly message.
///
/// `error_type` is the exception type name, `error_msg` is the message string,
/// `status` is the optional HTTP status code.
pub fn simplify_error(error_type: &str, error_msg: &str, status: Option<i32>) -> String {
    // Unexpected keyword argument.
    if is_unexpected_keyword_error(error_msg) {
        if let Some(name) = unexpected_kwarg_name(error_msg) {
            return format!(
                "Unexpected argument '{name}'. \
                 Omit unknown parameters and retry with only the documented tool inputs."
            );
        }
        return "Unexpected tool argument. \
            Omit unknown parameters and retry with only the documented tool inputs."
            .to_string();
    }

    // Missing required argument.
    if error_type == "TypeError"
        && (error_msg.contains("required positional argument")
            || error_msg.contains("required keyword-only argument"))
    {
        if let Some(count) = missing_required_count(error_msg) {
            return format!(
                "Missing {count} required argument(s). \
                 Check the tool schema and retry with the documented inputs."
            );
        }
        return "Missing required argument(s). Check the tool schema and retry.".to_string();
    }

    // DNS/Network errors.
    if error_msg.contains("nodename nor servname") {
        return "DNS resolution failed - invalid domain name".to_string();
    }
    if error_type.contains("ConnectError") || error_type.contains("ConnectionError") {
        if error_msg.contains("Connection refused") {
            return "Connection refused - service may not be running".to_string();
        }
        return "Connection failed - network unreachable or service down".to_string();
    }
    if error_type.contains("Timeout") || error_msg.to_lowercase().contains("timeout") {
        return "Request timed out".to_string();
    }

    // HTTP errors — check status.
    if let Some(s) = status {
        return format!("HTTP error {s}");
    }

    // Default: show type and message.
    format!("{error_type}: {error_msg}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unexpected_keyword_detected() {
        assert!(is_unexpected_keyword_error(
            "got an unexpected keyword argument 'limit'"
        ));
        assert!(!is_unexpected_keyword_error("some other error"));
    }

    #[test]
    fn kwarg_name_single_quotes() {
        let name = unexpected_kwarg_name("got an unexpected keyword argument 'limit'");
        assert_eq!(name, Some("limit".to_string()));
    }

    #[test]
    fn kwarg_name_double_quotes() {
        let name = unexpected_kwarg_name("got an unexpected keyword argument \"count\"");
        assert_eq!(name, Some("count".to_string()));
    }

    #[test]
    fn kwarg_name_none_when_no_match() {
        assert!(unexpected_kwarg_name("no keyword here").is_none());
    }

    #[test]
    fn missing_required_count_extracted() {
        let msg = "missing 2 required positional arguments: 'a' and 'b'";
        assert_eq!(missing_required_count(msg), Some("2".to_string()));
    }

    #[test]
    fn missing_required_count_none_when_no_count() {
        let msg = "missing required positional argument";
        assert!(missing_required_count(msg).is_none());
    }

    #[test]
    fn is_llm_argument_error_true_for_unexpected_kwarg() {
        assert!(is_llm_argument_error(
            "TypeError",
            "got an unexpected keyword argument 'limit'"
        ));
    }

    #[test]
    fn is_llm_argument_error_false_for_non_typeerror() {
        assert!(!is_llm_argument_error("ValueError", "some error"));
    }

    #[test]
    fn warning_level_for_403() {
        assert!(is_warning_level_error("HTTPError", "forbidden", Some(403)));
    }

    #[test]
    fn warning_level_for_429() {
        assert!(is_warning_level_error(
            "HTTPError",
            "rate limited",
            Some(429)
        ));
    }

    #[test]
    fn warning_level_for_llm_arg_error() {
        assert!(is_warning_level_error(
            "TypeError",
            "got an unexpected keyword argument 'limit'",
            None
        ));
    }

    #[test]
    fn warning_level_false_for_generic_error() {
        assert!(!is_warning_level_error("ValueError", "bad value", None));
    }

    #[test]
    fn simplify_unexpected_kwarg_with_name() {
        let result = simplify_error(
            "TypeError",
            "got an unexpected keyword argument 'limit'",
            None,
        );
        assert!(result.contains("Unexpected argument 'limit'"));
    }

    #[test]
    fn simplify_unexpected_kwarg_without_name() {
        let result = simplify_error("TypeError", "unexpected keyword argument somewhere", None);
        assert!(result.contains("Unexpected tool argument"));
    }

    #[test]
    fn simplify_missing_required_with_count() {
        let result = simplify_error("TypeError", "missing 2 required positional arguments", None);
        assert!(result.contains("Missing 2 required argument(s)"));
    }

    #[test]
    fn simplify_dns_error() {
        let result = simplify_error("ConnectionError", "nodename nor servname provided", None);
        assert_eq!(result, "DNS resolution failed - invalid domain name");
    }

    #[test]
    fn simplify_connection_refused() {
        let result = simplify_error("ConnectError", "Connection refused", None);
        assert_eq!(result, "Connection refused - service may not be running");
    }

    #[test]
    fn simplify_connection_failed() {
        let result = simplify_error("ConnectionError", "network unreachable", None);
        assert_eq!(
            result,
            "Connection failed - network unreachable or service down"
        );
    }

    #[test]
    fn simplify_timeout_by_type() {
        let result = simplify_error("ReadTimeoutError", "took too long", None);
        assert_eq!(result, "Request timed out");
    }

    #[test]
    fn simplify_timeout_by_message() {
        let result = simplify_error("CustomError", "request timeout occurred", None);
        assert_eq!(result, "Request timed out");
    }

    #[test]
    fn simplify_http_error_with_status() {
        let result = simplify_error("HTTPError", "server error", Some(500));
        assert_eq!(result, "HTTP error 500");
    }

    #[test]
    fn simplify_default_type_and_message() {
        let result = simplify_error("ValueError", "bad value", None);
        assert_eq!(result, "ValueError: bad value");
    }
}
