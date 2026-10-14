//! Pure path helpers: virtual-resolution gating, workspace joins, SQLite layout.
//!
//! Ported from `workspace_paths.py` and `paths/__init__.py`. These functions
//! are pure (no FS mutation); they compute paths and let callers materialize.

use crate::WorkspaceError;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
#[cfg(test)]
use std::sync::Mutex;
use std::sync::OnceLock;

/// Product layout under the workspace (not soothe-deepagents defaults).
pub const WORKSPACE_BACKUP_DIR: &str = ".soothe/backups";

/// SQLite purpose databases live under `databases/`.
pub const SQLITE_DATABASES_SUBDIR: &str = "databases";

/// Serializes tests that mutate `SOOTHE_HOME` / `SOOTHE_DATA_DIR` env vars.
#[cfg(test)]
static ENV_LOCK: Mutex<()> = Mutex::new(());

/// Top-level Unix host root directory names.
///
/// When a leading-`/` path's first segment is one of these, it is treated as a
/// real host path rather than a virtual sandbox path.
static _UNIX_HOST_ROOT_TOP_NAMES: OnceLock<HashSet<&'static str>> = OnceLock::new();

/// Borrow the static set of Unix host root top names.
fn unix_host_root_top_names() -> &'static HashSet<&'static str> {
    _UNIX_HOST_ROOT_TOP_NAMES.get_or_init(|| {
        const NAMES: &[&str] = &[
            "Applications",
            "bin",
            "cores",
            "dev",
            "etc",
            "home",
            "Library",
            "opt",
            "private",
            "sbin",
            "sys",
            "System",
            "tmp",
            "usr",
            "Users",
            "var",
            "Volumes",
        ];
        NAMES.iter().copied().collect()
    })
}

/// Return the first path segment name of an absolute POSIX path, or `None`.
///
/// Mirrors `_posix_first_segment_name`: returns `None` when the path is not
/// absolute or has no segment after the root.
pub fn posix_first_segment_name(expanded: &Path) -> Option<&str> {
    use std::path::Component;
    let mut components = expanded.components();
    match components.next() {
        Some(Component::RootDir) => {}
        _ => return None,
    }
    match components.next() {
        Some(Component::Normal(seg)) => seg.to_str(),
        _ => None,
    }
}

/// Expand a leading `~` to `$HOME` (best-effort; no-op without HOME).
fn expanduser(path: &str) -> String {
    if path.starts_with('~') {
        if let Ok(home) = std::env::var("HOME") {
            if path == "~" {
                return home;
            }
            if let Some(stripped) = path.strip_prefix("~/") {
                return format!("{home}/{stripped}");
            }
        }
    }
    path.to_string()
}

/// True when a leading-`/` path should use virtual sandbox resolution.
///
/// Mirrors `should_use_virtual_path_resolution`:
/// - Non-absolute paths never need virtual resolution.
/// - If the resolved path is already under the workspace root, it is real.
/// - Otherwise, if the first segment is a known Unix host root top name
///   (e.g. `etc`, `usr`, `tmp`), treat it as a real host path (return false).
/// - If there is no first segment (bare `/`) or it is not a host root name,
///   treat it as a virtual path (return true).
pub fn should_use_virtual_path_resolution(file_path: &str, workspace_root: &Path) -> bool {
    let trimmed = file_path.trim();
    if !trimmed.starts_with('/') {
        return false;
    }
    let expanded = PathBuf::from(expanduser(trimmed));

    // If the expanded path resolves under the workspace root, it is real.
    let resolved = expanded.canonicalize().unwrap_or_else(|_| expanded.clone());
    let root_resolved = workspace_root
        .canonicalize()
        .unwrap_or_else(|_| workspace_root.to_path_buf());
    if resolved.starts_with(&root_resolved) {
        return false;
    }

    match posix_first_segment_name(&expanded) {
        None => true,
        Some(first) => !unix_host_root_top_names().contains(first),
    }
}

/// Convert a validator-normalized logical path to an on-disk path.
///
/// Mirrors `join_workspace_normalized_path`:
/// - Absolute normalized paths are resolved as-is (no escape check).
/// - Relative paths are joined under the workspace and resolved.
/// - `..` escapes in relative paths are rejected via `normalize_relative`.
pub fn join_workspace_normalized_path(
    workspace: &Path,
    normalized: &str,
) -> Result<PathBuf, WorkspaceError> {
    let path = Path::new(normalized);
    if path.is_absolute() {
        return Ok(path.canonicalize().unwrap_or_else(|_| path.to_path_buf()));
    }
    let cleaned =
        soothe_nano_utils::normalize_relative(normalized).map_err(WorkspaceError::InvalidPath)?;
    let joined = workspace.join(&cleaned);
    Ok(joined.canonicalize().unwrap_or(joined))
}

/// Resolve `$SOOTHE_DATA_DIR`. Precedence: env var > `$SOOTHE_HOME/data`.
pub fn soothe_data_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("SOOTHE_DATA_DIR") {
        return PathBuf::from(dir);
    }
    crate::sqlite_paths::soothe_home().join("data")
}

/// Return `$SOOTHE_DATA_DIR/databases` (creates nothing).
pub fn resolve_databases_dir() -> PathBuf {
    soothe_data_dir().join(SQLITE_DATABASES_SUBDIR)
}

/// Return `$SOOTHE_DATA_DIR/databases/{purpose}.db`.
///
/// Strips whitespace and a trailing `.db` suffix from `purpose`.
pub fn resolve_sqlite_db_path(purpose: &str) -> PathBuf {
    let name = purpose.trim().trim_end_matches(".db");
    resolve_databases_dir().join(format!("{name}.db"))
}

// --- Purpose-specific DB path helpers (ported from paths/__init__.py) ---

/// StrangeLoop / loop checkpoints SQLite path.
pub fn resolve_checkpoints_db_path() -> PathBuf {
    resolve_sqlite_db_path("checkpoints")
}

/// Context Engine SQLite path.
pub fn resolve_context_db_path() -> PathBuf {
    resolve_sqlite_db_path("context")
}

/// Display card ledger SQLite path.
pub fn resolve_display_db_path() -> PathBuf {
    resolve_sqlite_db_path("display")
}

/// Cron job store SQLite path.
pub fn resolve_cron_db_path() -> PathBuf {
    resolve_sqlite_db_path("cron")
}

/// Identity service SQLite path.
pub fn resolve_identity_db_path() -> PathBuf {
    resolve_sqlite_db_path("identity")
}

/// ThreadInfo / durability metadata SQLite path.
pub fn resolve_metadata_db_path() -> PathBuf {
    resolve_sqlite_db_path("metadata")
}

/// Persist KV SQLite path.
pub fn resolve_persist_db_path() -> PathBuf {
    resolve_sqlite_db_path("persist")
}

/// Vector store (sqlite-vec) SQLite path.
pub fn resolve_vectors_db_path() -> PathBuf {
    resolve_sqlite_db_path("vectors")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sqlite_paths::{db_path_for_thread, default_db_path};

    /// Helper: acquire the env-lock for the duration of a closure.
    fn with_env_lock<F: FnOnce()>(f: F) {
        let _guard = ENV_LOCK.lock().unwrap();
        f();
    }

    // --- posix_first_segment_name ---

    #[test]
    fn first_segment_absolute() {
        assert_eq!(
            posix_first_segment_name(Path::new("/etc/passwd")),
            Some("etc")
        );
    }

    #[test]
    fn first_segment_bare_root() {
        assert_eq!(posix_first_segment_name(Path::new("/")), None);
    }

    #[test]
    fn first_segment_relative() {
        assert_eq!(posix_first_segment_name(Path::new("etc/passwd")), None);
    }

    #[test]
    fn first_segment_empty() {
        assert_eq!(posix_first_segment_name(Path::new("")), None);
    }

    // --- should_use_virtual_path_resolution ---

    #[test]
    fn virtual_resolution_relative_returns_false() {
        let ws = Path::new("/tmp/ws");
        assert!(!should_use_virtual_path_resolution("relative/path", ws));
        assert!(!should_use_virtual_path_resolution("./x", ws));
    }

    #[test]
    fn virtual_resolution_host_root_name_returns_false() {
        let ws = Path::new("/tmp/ws");
        // `etc` is a known host root top name -> real host path.
        assert!(!should_use_virtual_path_resolution("/etc/passwd", ws));
        assert!(!should_use_virtual_path_resolution("/usr/bin", ws));
        assert!(!should_use_virtual_path_resolution("/tmp/foo", ws));
    }

    #[test]
    fn virtual_resolution_unknown_top_name_returns_true() {
        let ws = Path::new("/tmp/ws");
        assert!(should_use_virtual_path_resolution("/virtual/thing", ws));
    }

    #[test]
    fn virtual_resolution_bare_slash_returns_true() {
        let ws = Path::new("/tmp/ws");
        assert!(should_use_virtual_path_resolution("/", ws));
    }

    // --- join_workspace_normalized_path ---

    #[test]
    fn join_relative() {
        let ws = Path::new("/tmp/workspace");
        let p = join_workspace_normalized_path(ws, "a/b/c").unwrap();
        assert!(p.starts_with("/tmp/workspace"));
        assert!(p.to_string_lossy().ends_with("a/b/c"));
    }

    #[test]
    fn join_rejects_escape() {
        let ws = Path::new("/tmp/workspace");
        assert!(join_workspace_normalized_path(ws, "../../etc").is_err());
    }

    #[test]
    fn join_strips_curdir() {
        let ws = Path::new("/tmp/workspace");
        let p = join_workspace_normalized_path(ws, "./a").unwrap();
        assert!(p.to_string_lossy().ends_with("a"));
    }

    #[test]
    fn join_absolute_not_rejected() {
        // Absolute paths bypass normalize_relative and resolve as-is.
        let ws = Path::new("/tmp/workspace");
        let p = join_workspace_normalized_path(ws, "/tmp/workspace/README.md").unwrap();
        assert!(p.is_absolute());
    }

    // --- soothe_home / soothe_data_dir ---

    #[test]
    fn soothe_data_dir_default() {
        with_env_lock(|| {
            std::env::remove_var("SOOTHE_DATA_DIR");
            std::env::set_var("SOOTHE_HOME", "/custom/soothe");
            assert_eq!(soothe_data_dir(), PathBuf::from("/custom/soothe/data"));
            std::env::remove_var("SOOTHE_HOME");
        });
    }

    #[test]
    fn soothe_data_dir_env_override() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_DATA_DIR", "/data/soothe");
            assert_eq!(soothe_data_dir(), PathBuf::from("/data/soothe"));
            std::env::remove_var("SOOTHE_DATA_DIR");
        });
    }

    // --- resolve_databases_dir / resolve_sqlite_db_path ---

    #[test]
    fn databases_dir_default() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_HOME", "/custom/soothe");
            std::env::remove_var("SOOTHE_DATA_DIR");
            assert_eq!(
                resolve_databases_dir(),
                PathBuf::from("/custom/soothe/data/databases")
            );
            std::env::remove_var("SOOTHE_HOME");
        });
    }

    #[test]
    fn sqlite_db_path_strips_db_suffix() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_DATA_DIR", "/data/soothe");
            assert_eq!(
                resolve_sqlite_db_path("checkpoints.db"),
                PathBuf::from("/data/soothe/databases/checkpoints.db")
            );
            std::env::remove_var("SOOTHE_DATA_DIR");
        });
    }

    #[test]
    fn sqlite_db_path_trims_whitespace() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_DATA_DIR", "/data/soothe");
            assert_eq!(
                resolve_sqlite_db_path("  persist  "),
                PathBuf::from("/data/soothe/databases/persist.db")
            );
            std::env::remove_var("SOOTHE_DATA_DIR");
        });
    }

    // --- purpose-specific helpers ---

    #[test]
    fn purpose_db_paths() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_DATA_DIR", "/data/soothe");
            assert_eq!(
                resolve_checkpoints_db_path(),
                PathBuf::from("/data/soothe/databases/checkpoints.db")
            );
            assert_eq!(
                resolve_context_db_path(),
                PathBuf::from("/data/soothe/databases/context.db")
            );
            assert_eq!(
                resolve_display_db_path(),
                PathBuf::from("/data/soothe/databases/display.db")
            );
            assert_eq!(
                resolve_cron_db_path(),
                PathBuf::from("/data/soothe/databases/cron.db")
            );
            assert_eq!(
                resolve_identity_db_path(),
                PathBuf::from("/data/soothe/databases/identity.db")
            );
            assert_eq!(
                resolve_metadata_db_path(),
                PathBuf::from("/data/soothe/databases/metadata.db")
            );
            assert_eq!(
                resolve_persist_db_path(),
                PathBuf::from("/data/soothe/databases/persist.db")
            );
            assert_eq!(
                resolve_vectors_db_path(),
                PathBuf::from("/data/soothe/databases/vectors.db")
            );
            std::env::remove_var("SOOTHE_DATA_DIR");
        });
    }

    // --- default_db_path / db_path_for_thread ---

    #[test]
    fn default_db_path_uses_soothe_home() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_HOME", "/tmp/soothe");
            assert_eq!(default_db_path(), PathBuf::from("/tmp/soothe/nano.db"));
            std::env::remove_var("SOOTHE_HOME");
        });
    }

    #[test]
    fn thread_db_path() {
        with_env_lock(|| {
            std::env::set_var("SOOTHE_HOME", "/tmp/soothe");
            assert_eq!(
                db_path_for_thread("abc-123"),
                PathBuf::from("/tmp/soothe/threads/abc-123.db")
            );
            std::env::remove_var("SOOTHE_HOME");
        });
    }

    // --- unix_host_root_top_names coverage ---

    #[test]
    fn host_root_names_recognized() {
        let names = unix_host_root_top_names();
        for known in [
            "Applications",
            "bin",
            "etc",
            "usr",
            "tmp",
            "Users",
            "Volumes",
        ] {
            assert!(names.contains(known), "missing {known}");
        }
        assert!(!names.contains("virtual"));
    }
}
