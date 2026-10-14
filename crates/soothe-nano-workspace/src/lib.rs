//! Path resolution and workspace isolation.

pub mod paths;
pub mod policy;
pub mod resolution;
pub mod sqlite_paths;

pub use paths::{
    join_workspace_normalized_path, posix_first_segment_name, resolve_checkpoints_db_path,
    resolve_context_db_path, resolve_cron_db_path, resolve_databases_dir, resolve_display_db_path,
    resolve_identity_db_path, resolve_metadata_db_path, resolve_persist_db_path,
    resolve_sqlite_db_path, resolve_vectors_db_path, should_use_virtual_path_resolution,
    soothe_data_dir, SQLITE_DATABASES_SUBDIR, WORKSPACE_BACKUP_DIR,
};
pub use policy::WorkspacePolicy;
pub use resolution::{resolve_workspace_for_stream, ResolvedWorkspace, WorkspaceSource};
pub use sqlite_paths::{db_path_for_thread, default_db_path, soothe_home};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum WorkspaceError {
    #[error("path escapes workspace boundary: {0}")]
    PathEscape(String),
    #[error("workspace not resolvable: no explicit, thread, or default workspace")]
    Unresolvable,
    #[error("invalid path: {0}")]
    InvalidPath(String),
}
