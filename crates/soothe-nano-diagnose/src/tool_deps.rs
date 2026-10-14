//! Host tool binary diagnose checks (rg, fd, git).

use std::process::Command;

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Return first line of `--version` output, or None on failure.
pub fn bin_version(bin_path: &str) -> Option<String> {
    let output = Command::new(bin_path).arg("--version").output().ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let combined = if stdout.trim().is_empty() {
        stderr
    } else {
        stdout
    };
    combined
        .lines()
        .next()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
}

/// Check a binary by path: returns (status, message, details_json).
pub fn check_binary(
    name: &str,
    path: Option<&str>,
    not_found_status: CheckStatus,
    not_found_msg: &str,
    not_found_remediation: &str,
) -> CheckResult {
    match path {
        None => CheckResult::with_details(
            name,
            not_found_status,
            not_found_msg,
            vec![(
                "remediation",
                serde_json::Value::String(not_found_remediation.into()),
            )],
        ),
        Some(p) => {
            let version = bin_version(p);
            let mut details = vec![("path", serde_json::Value::String(p.to_string()))];
            if let Some(ref v) = version {
                details.push(("version", serde_json::Value::String(v.clone())));
            }
            let msg = match &version {
                Some(v) => format!("{name} available: {p} ({v})"),
                None => format!("{name} available: {p}"),
            };
            CheckResult::with_details(name, CheckStatus::Ok, &msg, details)
        }
    }
}

/// Check ripgrep availability.
pub fn check_rg(rg_path: Option<&str>) -> CheckResult {
    check_binary(
        "rg",
        rg_path,
        CheckStatus::Warning,
        "rg (ripgrep) not found — search falls back to Python",
        "Install ripgrep (e.g. brew install ripgrep / apt install ripgrep)",
    )
}

/// Check fd / fdfind availability.
pub fn check_fd(fd_path: Option<&str>) -> CheckResult {
    check_binary(
        "fd",
        fd_path,
        CheckStatus::Warning,
        "fd not found — glob falls back to Python",
        "Install fd (e.g. brew install fd / apt install fd-find)",
    )
}

/// Check git binary (optional; used by many agent workflows).
pub fn check_git(git_path: Option<&str>) -> CheckResult {
    check_binary(
        "git",
        git_path,
        CheckStatus::Info,
        "git not found (optional)",
        "Install git if repository workflows are needed",
    )
}

/// Run all tool-dep checks and return a CategoryResult.
/// Python passes the resolved binary paths (from shutil.which / deepagents helpers).
pub fn check_tool_deps(
    rg_path: Option<&str>,
    fd_path: Option<&str>,
    git_path: Option<&str>,
) -> CategoryResult {
    let checks = vec![check_rg(rg_path), check_fd(fd_path), check_git(git_path)];
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("tool_deps", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn check_rg_not_found() {
        let r = check_rg(None);
        assert_eq!(r.status, CheckStatus::Warning);
        assert!(r.message.contains("not found"));
        assert!(r.details["remediation"].is_string());
    }

    #[test]
    fn check_rg_found_with_version() {
        // Use /bin/echo as a stand-in that always exists and produces output.
        let r = check_binary(
            "rg",
            Some("/bin/echo"),
            CheckStatus::Warning,
            "not found",
            "install",
        );
        assert_eq!(r.status, CheckStatus::Ok);
        assert!(r.details["path"].as_str() == Some("/bin/echo"));
        // echo --version outputs "--version" on macOS, but the line is non-empty.
        assert!(r.details["version"].is_string());
    }

    #[test]
    fn check_git_not_found_is_info() {
        let r = check_git(None);
        assert_eq!(r.status, CheckStatus::Info);
    }

    #[test]
    fn check_tool_deps_aggregates() {
        let cat = check_tool_deps(None, None, None);
        assert_eq!(cat.category, "tool_deps");
        assert_eq!(cat.status, CheckStatus::Warning); // rg/fd warnings > git info
        assert_eq!(cat.checks.len(), 3);
    }

    #[test]
    fn bin_version_nonexistent_returns_none() {
        assert!(bin_version("/nonexistent/binary/xyz").is_none());
    }
}
