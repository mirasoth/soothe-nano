//! SQLite path resolution (ported from `paths/sqlite_paths.py`).
//!
//! Resolves the `SOOTHE_HOME` directory and thread-specific DB file layout.

use std::path::PathBuf;

/// Resolve `SOOTHE_HOME`. Precedence: env var > `~/.soothe`.
pub fn soothe_home() -> PathBuf {
    if let Ok(dir) = std::env::var("SOOTHE_HOME") {
        return PathBuf::from(dir);
    }
    if let Some(home) = dirs_or_default() {
        return home.join(".soothe");
    }
    PathBuf::from(".soothe")
}

/// Path to the default (non-thread-scoped) SQLite DB.
pub fn default_db_path() -> PathBuf {
    soothe_home().join("nano.db")
}

/// Path to a thread-scoped SQLite DB file.
pub fn db_path_for_thread(thread_id: &str) -> PathBuf {
    soothe_home()
        .join("threads")
        .join(format!("{thread_id}.db"))
}

fn dirs_or_default() -> Option<PathBuf> {
    std::env::var("HOME").ok().map(PathBuf::from)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_overrides_home() {
        std::env::set_var("SOOTHE_HOME", "/custom/soothe");
        assert_eq!(soothe_home(), PathBuf::from("/custom/soothe"));
        std::env::remove_var("SOOTHE_HOME");
    }

    #[test]
    fn thread_db_path() {
        std::env::set_var("SOOTHE_HOME", "/tmp/soothe");
        let p = db_path_for_thread("abc-123");
        assert_eq!(p, PathBuf::from("/tmp/soothe/threads/abc-123.db"));
        std::env::remove_var("SOOTHE_HOME");
    }
}
