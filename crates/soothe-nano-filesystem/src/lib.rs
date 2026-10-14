//! Local filesystem operations: read, write, edit, grep, glob.

pub mod discovery_hints;
pub mod file_ops;
pub mod glob;
pub mod grep;
pub mod local;

pub use file_ops::{BatchedEditResult, EditOp, EditResult, ReadResult, WriteResult};
pub use glob::GlobResult;
pub use grep::{GrepMatch, GrepResult};
pub use local::LocalFilesystem;
