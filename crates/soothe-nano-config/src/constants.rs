//! Constants (ported from `config/constants.py`).

pub const SOOTHE_NANO_VERSION: &str = env!("CARGO_PKG_VERSION");

pub const DEFAULT_MAX_ITERATIONS: u32 = 25;
pub const DEFAULT_RECURSION_LIMIT: u32 = 40;
pub const DEFAULT_MAX_FILE_SIZE: u64 = 10 * 1024 * 1024; // 10 MiB
pub const DEFAULT_RATE_LIMIT_PER_MINUTE: u32 = 60;

pub const DEFAULT_SQLITE_PATH: &str = "~/.soothe/nano.db";

pub const ENV_SOOTHE_HOME: &str = "SOOTHE_HOME";
pub const ENV_SOOTHE_CONFIG: &str = "SOOTHE_CONFIG";

/// Upper bound for per-call run_command timeout (5 hours).
pub const MAX_EXECUTE_TIMEOUT: i64 = 18_000;

/// Clamp a timeout value to `MAX_EXECUTE_TIMEOUT`.
pub fn clamp_timeout(seconds: i64) -> i64 {
    seconds.min(MAX_EXECUTE_TIMEOUT)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamp_below_ceiling() {
        assert_eq!(clamp_timeout(60), 60);
        assert_eq!(clamp_timeout(0), 0);
    }

    #[test]
    fn clamp_at_ceiling() {
        assert_eq!(clamp_timeout(MAX_EXECUTE_TIMEOUT), MAX_EXECUTE_TIMEOUT);
    }

    #[test]
    fn clamp_above_ceiling() {
        assert_eq!(clamp_timeout(99_999), MAX_EXECUTE_TIMEOUT);
    }

    #[test]
    fn clamp_negative() {
        assert_eq!(clamp_timeout(-5), -5);
    }
}
