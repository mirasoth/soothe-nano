//! Path resolution and workspace isolation.

pub mod policy;
pub mod resolution;
pub mod sqlite_paths;

pub use policy::WorkspacePolicy;
pub use resolution::{
    join_workspace_normalized_path, resolve_workspace_for_stream, ResolvedWorkspace,
    WorkspaceSource,
};
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
