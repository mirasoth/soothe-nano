//! Constants (ported from `config/constants.py`).

pub const SOOTHE_NANO_VERSION: &str = env!("CARGO_PKG_VERSION");

pub const DEFAULT_MAX_ITERATIONS: u32 = 25;
pub const DEFAULT_RECURSION_LIMIT: u32 = 40;
pub const DEFAULT_MAX_FILE_SIZE: u64 = 10 * 1024 * 1024; // 10 MiB
pub const DEFAULT_RATE_LIMIT_PER_MINUTE: u32 = 60;

pub const DEFAULT_SQLITE_PATH: &str = "~/.soothe/nano.db";

pub const ENV_SOOTHE_HOME: &str = "SOOTHE_HOME";
pub const ENV_SOOTHE_CONFIG: &str = "SOOTHE_CONFIG";
