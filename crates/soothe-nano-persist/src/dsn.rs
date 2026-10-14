//! PostgreSQL DSN manipulation (ported from `postgres_provisioning.py`).

use crate::sql_parsing::is_valid_db_name;

/// Parsed DSN components.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DsnParts {
    pub scheme: String,
    pub netloc: String,
    pub path: String,
    pub query: String,
    pub fragment: String,
}

/// Parse a DSN into its components.
///
/// Handles `postgresql://user:pass@host:port/dbname?param=val` style DSNs.
/// Returns `None` if the DSN has no scheme separator.
pub fn parse_dsn(dsn: &str) -> Option<DsnParts> {
    let dsn = dsn.trim_end_matches('/');
    let scheme_end = dsn.find("://")?;
    let scheme = dsn[..scheme_end].to_string();
    let rest = &dsn[scheme_end + 3..];

    let (authority, after_auth) = match rest.find('?') {
        Some(q) => (&rest[..q], &rest[q..]),
        None => (rest, ""),
    };

    let (netloc, path_part) = match authority.find('/') {
        Some(s) => (&authority[..s], &authority[s..]),
        None => (authority, ""),
    };

    // Build the full path+query+fragment string
    let path_query_fragment = if after_auth.is_empty() {
        path_part.to_string()
    } else {
        format!("{path_part}{after_auth}")
    };

    // Split path from query
    let (path, query_fragment) = match path_query_fragment.find('?') {
        Some(q) => (
            path_query_fragment[..q].to_string(),
            &path_query_fragment[q..],
        ),
        None => (path_query_fragment.clone(), ""),
    };

    // Split query from fragment
    let (query, fragment) = match query_fragment.find('#') {
        Some(f) => (
            query_fragment[..f].to_string(),
            query_fragment[f..].to_string(),
        ),
        None => (query_fragment.to_string(), String::new()),
    };

    Some(DsnParts {
        scheme,
        netloc: netloc.to_string(),
        path,
        query,
        fragment,
    })
}

/// Build a DSN targeting the `postgres` maintenance database.
pub fn admin_dsn(base_dsn: &str) -> Option<String> {
    let parts = parse_dsn(base_dsn)?;
    Some(format!(
        "{}://{}{}{}",
        parts.scheme, parts.netloc, "/postgres", parts.query
    ))
}

/// Build a DSN targeting a named database under `base_dsn`.
///
/// Returns `None` if `database_name` is not a valid identifier.
pub fn target_dsn(base_dsn: &str, database_name: &str) -> Option<String> {
    if !is_valid_db_name(database_name) {
        return None;
    }
    let parts = parse_dsn(base_dsn)?;
    Some(format!(
        "{}://{}{}{}{}",
        parts.scheme, parts.netloc, "/", database_name, parts.query
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_dsn() {
        let parts = parse_dsn("postgresql://localhost:5432").unwrap();
        assert_eq!(parts.scheme, "postgresql");
        assert_eq!(parts.netloc, "localhost:5432");
        assert_eq!(parts.path, "");
    }

    #[test]
    fn test_parse_dsn_with_db() {
        let parts = parse_dsn("postgresql://user:pass@host:5432/mydb?sslmode=require").unwrap();
        assert_eq!(parts.scheme, "postgresql");
        assert_eq!(parts.netloc, "user:pass@host:5432");
        assert_eq!(parts.path, "/mydb");
        assert_eq!(parts.query, "?sslmode=require");
    }

    #[test]
    fn test_parse_dsn_no_scheme() {
        assert!(parse_dsn("localhost:5432").is_none());
    }

    #[test]
    fn test_admin_dsn() {
        let dsn = admin_dsn("postgresql://user:pass@host:5432/mydb").unwrap();
        assert_eq!(dsn, "postgresql://user:pass@host:5432/postgres");
    }

    #[test]
    fn test_admin_dsn_with_query() {
        let dsn = admin_dsn("postgresql://host:5432/mydb?sslmode=require").unwrap();
        assert_eq!(dsn, "postgresql://host:5432/postgres?sslmode=require");
    }

    #[test]
    fn test_target_dsn() {
        let dsn = target_dsn("postgresql://host:5432", "soothe_metadata").unwrap();
        assert_eq!(dsn, "postgresql://host:5432/soothe_metadata");
    }

    #[test]
    fn test_target_dsn_invalid_name() {
        assert!(target_dsn("postgresql://host:5432", "1bad").is_none());
        assert!(target_dsn("postgresql://host:5432", "has-dash").is_none());
    }
}
