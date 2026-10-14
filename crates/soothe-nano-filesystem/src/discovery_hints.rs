//! Discovery guidance for filesystem tool descriptions and error recovery.

/// Glob discovery fallback hint — guidance appended to glob tool description
/// and embedded in glob timeout errors.
pub const GLOB_DISCOVERY_FALLBACK_HINT: &str = "If glob fails, times out, or returns empty: narrow the path (e.g. packages/foo/), use grep(pattern=..., glob='*.ts') for content-based discovery, or ls on known directories before read_file on specific targets. Avoid repeating broad ** globs.";

/// Grep discovery fallback hint — guidance appended to grep tool description.
pub const GREP_DISCOVERY_FALLBACK_HINT: &str = "Prefer this grep tool over run_command with grep/rg for content search. Batch parallel grep calls for multiple patterns. Scope with path/glob when known. Only if you need true regex or flags this tool lacks: run_command with `rg '<regex>' <path>` (always pass an explicit path after the pattern).";

/// Glob tool description.
pub const GLOB_TOOL_DESCRIPTION: &str = concat!(
    "Find files and directories matching a glob pattern.\n",
    "\n",
    "Supports standard glob patterns: `*` (any characters), `**` (any directories), `?` (single character).\n",
    "A trailing `/` means directories only (e.g. `packages/*/`). Otherwise matching files and directories\n",
    "are returned (`is_dir` marks directories).\n",
    "\n",
    "Prefer narrow patterns scoped to a directory (e.g. `packages/foo/**/*.test.ts`) over repo-wide `**` scans.\n",
    "Set `path` to a subdirectory when the search target is known.\n",
    "\n",
    "Examples:\n",
    "- `**/*.py` - Find all Python files (may be slow on large repos)\n",
    "- `packages/*/` - Package directories under packages/\n",
    "- `packages/api/**/*.test.ts` - TypeScript tests under one package\n",
    "- `*.txt` - Text files in the search root\n",
    "\n",
    "If glob fails, times out, or returns empty: narrow the path (e.g. packages/foo/), use grep(pattern=..., glob='*.ts') for content-based discovery, or ls on known directories before read_file on specific targets. Avoid repeating broad ** globs."
);

/// Grep tool description.
pub const GREP_TOOL_DESCRIPTION: &str = concat!(
    "Search for a LITERAL text pattern across files (NOT regex).\n",
    "\n",
    "Uses ripgrep when available, with a Python fallback. Prefer this tool over shell\n",
    "`grep`/`rg`/`find` for routine repo content search.\n",
    "\n",
    "Args:\n",
    "- pattern: Literal string to find (fixed-string; special regex chars are matched literally)\n",
    "- path: Optional file or directory to search (default: workspace root)\n",
    "- glob: Optional filename filter (e.g. `*.py`, `**/*.ts`)\n",
    "\n",
    "Tips:\n",
    "- Batch multiple patterns as parallel grep tool calls in one step\n",
    "- Narrow with path and/or glob when the target area is known\n",
    "- For path-only discovery, use glob instead\n",
    "\n",
    "Prefer this grep tool over run_command with grep/rg for content search. Batch parallel grep calls for multiple patterns. Scope with path/glob when known. Only if you need true regex or flags this tool lacks: run_command with `rg '<regex>' <path>` (always pass an explicit path after the pattern)."
);

/// Build a glob timeout error with discovery fallback guidance.
pub fn format_glob_timeout_error(timeout_seconds: f64) -> String {
    format!(
        "Error: glob timed out after {:.0}s. Try a more specific pattern, set path to a narrower directory, or switch strategy: {}",
        timeout_seconds, GLOB_DISCOVERY_FALLBACK_HINT
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn glob_description_includes_fallback_hint() {
        assert!(GLOB_TOOL_DESCRIPTION.contains(GLOB_DISCOVERY_FALLBACK_HINT));
        assert!(GLOB_TOOL_DESCRIPTION.contains("grep"));
    }

    #[test]
    fn grep_description_includes_fallback_hint() {
        assert!(GREP_TOOL_DESCRIPTION.contains(GREP_DISCOVERY_FALLBACK_HINT));
        assert!(GREP_TOOL_DESCRIPTION.contains("LITERAL"));
        assert!(GREP_TOOL_DESCRIPTION.contains("run_command"));
    }

    #[test]
    fn format_glob_timeout_error_includes_seconds() {
        let msg = format_glob_timeout_error(30.0);
        assert!(msg.contains("timed out after 30s"));
        assert!(msg.contains(GLOB_DISCOVERY_FALLBACK_HINT));
    }

    #[test]
    fn format_glob_timeout_error_no_decimal() {
        let msg = format_glob_timeout_error(5.7);
        assert!(msg.contains("timed out after 6s"));
    }
}
