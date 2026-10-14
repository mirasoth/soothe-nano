//! Retry error classification for PostgreSQL (ported from `retry_utils.py`).

/// Check if an error message indicates a duplicate schema error.
///
/// Detects concurrent DDL creation (UniqueViolation, DuplicateTable, etc.)
/// by pattern-matching the error message text.
pub fn is_duplicate_schema_error(exc_msg: &str) -> bool {
    let text = exc_msg.to_lowercase();
    let needles = [
        "duplicate key value violates unique constraint",
        "pg_type_typname_nsp_index",
        "already exists",
    ];
    needles.iter().any(|n| text.contains(n))
}

/// Check if an error message indicates a recoverable (transient) connection error.
///
/// Detects PostgreSQL server restarts, shutdowns, and connection failures
/// that are recoverable by reconnecting.
pub fn is_recoverable_connection_error(exc_msg: &str) -> bool {
    let text = exc_msg.to_lowercase();
    let needles = [
        "admin shutdown",
        "terminating connection due to administrator command",
        "connection is closed",
        "connection not open",
        "server closed the connection unexpectedly",
        "connection failure",
        "server is not running",
    ];
    needles.iter().any(|n| text.contains(n))
}

/// Compute exponential backoff delay for a retry attempt.
///
/// Returns the delay in seconds. Doubles each attempt, capped at `max_delay`.
pub fn backoff_delay(attempt: usize, base_delay: f64, max_delay: f64) -> f64 {
    let mut delay = base_delay;
    for _ in 1..attempt {
        delay = (delay * 2.0).min(max_delay);
    }
    delay
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_duplicate_schema_error() {
        assert!(is_duplicate_schema_error(
            "duplicate key value violates unique constraint"
        ));
        assert!(is_duplicate_schema_error("relation already exists"));
        assert!(!is_duplicate_schema_error("syntax error"));
    }

    #[test]
    fn test_recoverable_connection_error() {
        assert!(is_recoverable_connection_error(
            "admin shutdown: server shutting down"
        ));
        assert!(is_recoverable_connection_error("connection is closed"));
        assert!(is_recoverable_connection_error(
            "server closed the connection unexpectedly"
        ));
        assert!(!is_recoverable_connection_error("syntax error in SQL"));
    }

    #[test]
    fn test_backoff_delay() {
        assert_eq!(backoff_delay(1, 1.0, 8.0), 1.0);
        assert_eq!(backoff_delay(2, 1.0, 8.0), 2.0);
        assert_eq!(backoff_delay(3, 1.0, 8.0), 4.0);
        assert_eq!(backoff_delay(4, 1.0, 8.0), 8.0);
        assert_eq!(backoff_delay(5, 1.0, 8.0), 8.0);
    }
}
