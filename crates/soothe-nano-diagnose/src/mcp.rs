//! MCP server diagnose checks.

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// MCP transport types.
pub const TRANSPORT_STDIO: &str = "stdio";
pub const TRANSPORT_SSE: &str = "sse";
pub const TRANSPORT_STREAMABLE_HTTP: &str = "streamable_http";
pub const TRANSPORT_WEBSOCKET: &str = "websocket";

/// A simplified MCP server config for validation.
#[derive(Debug, Clone)]
pub struct McpServerSpec {
    pub name: String,
    pub transport: String,
    pub command: Option<String>,
    pub url: Option<String>,
}

/// Check result for no config loaded (skipped).
pub fn mcp_configs_no_config() -> CheckResult {
    CheckResult::new(
        "mcp_configs",
        CheckStatus::Skipped,
        "Skipped (no config loaded)",
    )
}

/// Check result for no MCP servers configured (info).
pub fn mcp_configs_empty() -> CheckResult {
    CheckResult::new(
        "mcp_configs",
        CheckStatus::Info,
        "No MCP servers configured",
    )
}

/// Validate MCP server configs.
///
/// Returns `(result, server_names)` so the caller can use names for availability checks.
pub fn check_mcp_configs(servers: &[McpServerSpec]) -> (CheckResult, Vec<String>) {
    if servers.is_empty() {
        return (mcp_configs_empty(), Vec::new());
    }

    let mut invalid: Vec<String> = Vec::new();
    for server in servers {
        if server.name.is_empty() {
            invalid.push("server missing name".into());
            continue;
        }
        let transport = if server.transport.is_empty() {
            TRANSPORT_STDIO
        } else {
            &server.transport
        };
        if transport == TRANSPORT_STDIO {
            if server.command.is_none() {
                invalid.push(format!(
                    "'{}' missing command for stdio transport",
                    server.name
                ));
            }
        } else if (transport == TRANSPORT_SSE
            || transport == TRANSPORT_STREAMABLE_HTTP
            || transport == TRANSPORT_WEBSOCKET)
            && server.url.is_none()
        {
            invalid.push(format!(
                "'{}' missing url for {} transport",
                server.name, transport
            ));
        }
    }

    let names: Vec<String> = servers.iter().map(|s| s.name.clone()).collect();

    if !invalid.is_empty() {
        return (
            CheckResult::with_details(
                "mcp_configs",
                CheckStatus::Error,
                &format!("Invalid MCP server configs: {}", invalid.join(", ")),
                vec![(
                    "remediation",
                    serde_json::Value::String("Fix MCP server configuration in config file".into()),
                )],
            ),
            names,
        );
    }

    (
        CheckResult::with_details(
            "mcp_configs",
            CheckStatus::Ok,
            &format!("{} MCP server(s) configured", servers.len()),
            vec![(
                "servers",
                serde_json::Value::Array(
                    names
                        .iter()
                        .map(|n| serde_json::Value::String(n.clone()))
                        .collect(),
                ),
            )],
        ),
        names,
    )
}

/// Check result for no config loaded (availability, skipped).
pub fn mcp_availability_no_config() -> CheckResult {
    CheckResult::new(
        "mcp_availability",
        CheckStatus::Skipped,
        "Skipped (no config loaded)",
    )
}

/// Check result for no MCP servers to check (info).
pub fn mcp_availability_empty() -> CheckResult {
    CheckResult::new(
        "mcp_availability",
        CheckStatus::Info,
        "No MCP servers to check",
    )
}

/// Check MCP server availability from availability data.
/// `availability_data` = (server_name, transport, command_or_url, is_available, is_remote)
pub fn check_mcp_availability(
    availability_data: &[(String, String, Option<String>, bool, bool)],
) -> CheckResult {
    if availability_data.is_empty() {
        return mcp_availability_empty();
    }

    let mut missing: Vec<String> = Vec::new();
    let mut available: Vec<String> = Vec::new();
    let mut remote: Vec<String> = Vec::new();

    for (name, _transport, cmd_or_url, is_available, is_remote) in availability_data {
        if *is_remote {
            remote.push(name.clone());
        } else if *is_available {
            available.push(name.clone());
        } else {
            let cmd = cmd_or_url.as_deref().unwrap_or("unknown");
            missing.push(format!("{name} ({cmd})"));
        }
    }

    if !missing.is_empty() {
        return CheckResult::with_details(
            "mcp_availability",
            CheckStatus::Warning,
            &format!("MCP servers not found: {}", missing.join(", ")),
            vec![
                (
                    "missing",
                    serde_json::Value::Array(
                        missing
                            .iter()
                            .map(|s| serde_json::Value::String(s.clone()))
                            .collect(),
                    ),
                ),
                (
                    "available",
                    serde_json::Value::Array(
                        available
                            .iter()
                            .map(|s| serde_json::Value::String(s.clone()))
                            .collect(),
                    ),
                ),
                (
                    "remote",
                    serde_json::Value::Array(
                        remote
                            .iter()
                            .map(|s| serde_json::Value::String(s.clone()))
                            .collect(),
                    ),
                ),
                (
                    "remediation",
                    serde_json::Value::String(
                        "Install missing MCP servers or update config".into(),
                    ),
                ),
            ],
        );
    }

    let mut msg_parts: Vec<String> = Vec::new();
    if !available.is_empty() {
        msg_parts.push(format!("{} stdio command(s) found", available.len()));
    }
    if !remote.is_empty() {
        msg_parts.push(format!("{} remote server(s)", remote.len()));
    }
    let message = if msg_parts.is_empty() {
        "No servers".to_string()
    } else {
        format!("All MCP servers: {}", msg_parts.join(", "))
    };

    CheckResult::with_details(
        "mcp_availability",
        CheckStatus::Ok,
        &message,
        vec![
            (
                "available",
                serde_json::Value::Array(
                    available
                        .iter()
                        .map(|s| serde_json::Value::String(s.clone()))
                        .collect(),
                ),
            ),
            (
                "remote",
                serde_json::Value::Array(
                    remote
                        .iter()
                        .map(|s| serde_json::Value::String(s.clone()))
                        .collect(),
                ),
            ),
        ],
    )
}

/// Build the mcp_servers category result from configs + availability checks.
pub fn check_mcp_servers_from_results(checks: Vec<CheckResult>) -> CategoryResult {
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("mcp_servers", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_config_is_skipped() {
        let r = mcp_configs_no_config();
        assert_eq!(r.status, CheckStatus::Skipped);
    }

    #[test]
    fn empty_configs_is_info() {
        let (r, names) = check_mcp_configs(&[]);
        assert_eq!(r.status, CheckStatus::Info);
        assert!(names.is_empty());
    }

    #[test]
    fn valid_stdio_config_is_ok() {
        let servers = vec![McpServerSpec {
            name: "test".into(),
            transport: "stdio".into(),
            command: Some("echo".into()),
            url: None,
        }];
        let (r, names) = check_mcp_configs(&servers);
        assert_eq!(r.status, CheckStatus::Ok);
        assert_eq!(names, vec!["test"]);
    }

    #[test]
    fn missing_command_is_error() {
        let servers = vec![McpServerSpec {
            name: "test".into(),
            transport: "stdio".into(),
            command: None,
            url: None,
        }];
        let (r, _) = check_mcp_configs(&servers);
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("missing command"));
    }

    #[test]
    fn missing_url_for_sse_is_error() {
        let servers = vec![McpServerSpec {
            name: "test".into(),
            transport: "sse".into(),
            command: None,
            url: None,
        }];
        let (r, _) = check_mcp_configs(&servers);
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("missing url"));
    }

    #[test]
    fn availability_all_found_is_ok() {
        let data = vec![
            (
                "srv1".into(),
                "stdio".into(),
                Some("echo".into()),
                true,
                false,
            ),
            (
                "srv2".into(),
                "sse".into(),
                Some("http://x".into()),
                false,
                true,
            ),
        ];
        let r = check_mcp_availability(&data);
        assert_eq!(r.status, CheckStatus::Ok);
        assert!(r.message.contains("All MCP servers"));
    }

    #[test]
    fn availability_missing_is_warning() {
        let data = vec![(
            "srv1".into(),
            "stdio".into(),
            Some("nonexist".into()),
            false,
            false,
        )];
        let r = check_mcp_availability(&data);
        assert_eq!(r.status, CheckStatus::Warning);
        assert!(r.message.contains("not found"));
    }

    #[test]
    fn check_mcp_servers_from_results_aggregates() {
        let checks = vec![mcp_configs_no_config(), mcp_availability_no_config()];
        let cat = check_mcp_servers_from_results(checks);
        assert_eq!(cat.category, "mcp_servers");
        assert_eq!(cat.status, CheckStatus::Skipped);
    }
}
