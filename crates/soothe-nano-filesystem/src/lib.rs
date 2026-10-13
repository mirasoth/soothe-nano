//! Local filesystem operations: read, write, edit, grep, glob.
//!
//! Ports: `filesystem/local.py`, `filesystem/unified.py`,
//! `toolkits/file_ops.py`, `toolkits/file_ops_catalog.py`.
//!
//! Uses the `ignore` crate for `.gitignore`-aware globbing (C implementation,
//! no Python pathspec/wcmatch dependency).

pub mod file_ops;
pub mod glob;
pub mod grep;
pub mod local;

pub use file_ops::{BatchedEditResult, EditOp, EditResult, ReadResult, WriteResult};
pub use glob::GlobResult;
pub use grep::{GrepMatch, GrepResult};
pub use local::LocalFilesystem;
