//! File operation result types.

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ReadResult {
    pub content: String,
    pub total_lines: usize,
    pub returned_lines: usize,
    pub offset: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct WriteResult {
    pub bytes_written: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct EditResult {
    pub replacements: usize,
}

#[derive(Debug, Clone)]
pub struct EditOp {
    pub path: String,
    pub old_string: String,
    pub new_string: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct BatchedEditResult {
    pub results: Vec<EditResult>,
    pub errors: Vec<String>,
}
