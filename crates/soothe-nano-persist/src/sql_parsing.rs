//! SQL script splitting and migration filename parsing.

use regex::Regex;
use std::sync::OnceLock;

static BLOCK_COMMENT: OnceLock<Regex> = OnceLock::new();
static MIGRATION_FILENAME: OnceLock<Regex> = OnceLock::new();

fn block_comment_re() -> &'static Regex {
    BLOCK_COMMENT.get_or_init(|| Regex::new(r"/\*.*?\*/s").expect("valid regex"))
}

fn migration_filename_re() -> &'static Regex {
    MIGRATION_FILENAME.get_or_init(|| Regex::new(r"^(\d{3})_(.+)\.sql$").expect("valid regex"))
}

/// Split an SQL script into individual statements.
///
/// Strips block comments (`/* ... */`) and line comments (`-- ...`),
/// then splits on semicolons. Returns non-empty trimmed statements in file order.
pub fn split_sql_statements(sql: &str) -> Vec<String> {
    let without_blocks = block_comment_re().replace_all(sql, "");
    let mut lines = Vec::new();
    for line in without_blocks.lines() {
        let stripped = if let Some(idx) = line.find("--") {
            &line[..idx]
        } else {
            line
        };
        lines.push(stripped);
    }
    let merged = lines.join("\n");
    merged
        .split(';')
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect()
}

/// Parsed versioned migration filename.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedMigrationFilename {
    pub version: String,
    pub name: String,
}

/// Parse a migration filename like `001_create_tables.sql`.
///
/// Returns `None` if the filename does not match the `NNN_name.sql` pattern.
pub fn parse_migration_filename(filename: &str) -> Option<ParsedMigrationFilename> {
    migration_filename_re()
        .captures(filename)
        .map(|caps| ParsedMigrationFilename {
            version: caps[1].to_string(),
            name: caps[2].to_string(),
        })
}

/// Validate a PostgreSQL database identifier.
///
/// Must start with a letter or underscore, followed by alphanumeric/underscore.
pub fn is_valid_db_name(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    let mut chars = name.chars();
    let first = chars.next().unwrap();
    if !(first.is_ascii_alphabetic() || first == '_') {
        return false;
    }
    chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_simple_statements() {
        let sql = "CREATE TABLE foo (id INT);\nCREATE TABLE bar (id INT);";
        let stmts = split_sql_statements(sql);
        assert_eq!(stmts.len(), 2);
        assert!(stmts[0].contains("foo"));
        assert!(stmts[1].contains("bar"));
    }

    #[test]
    fn test_split_with_line_comments() {
        let sql = "-- comment\nSELECT 1; -- another\nSELECT 2;";
        let stmts = split_sql_statements(sql);
        assert_eq!(stmts.len(), 2);
        assert_eq!(stmts[0], "SELECT 1");
        assert_eq!(stmts[1], "SELECT 2");
    }

    #[test]
    fn test_split_with_block_comments() {
        let sql = "/* block comment */\nSELECT 1;\n/* another */\nSELECT 2;";
        let stmts = split_sql_statements(sql);
        assert_eq!(stmts.len(), 2);
    }

    #[test]
    fn test_split_empty_sql() {
        assert!(split_sql_statements("").is_empty());
        assert!(split_sql_statements("-- only comment").is_empty());
    }

    #[test]
    fn test_parse_migration_filename_valid() {
        let parsed = parse_migration_filename("001_create_tables.sql").unwrap();
        assert_eq!(parsed.version, "001");
        assert_eq!(parsed.name, "create_tables");
    }

    #[test]
    fn test_parse_migration_filename_invalid() {
        assert!(parse_migration_filename("create_tables.sql").is_none());
        assert!(parse_migration_filename("init.sql").is_none());
        assert!(parse_migration_filename("01_foo.sql").is_none());
    }

    #[test]
    fn test_is_valid_db_name() {
        assert!(is_valid_db_name("soothe_metadata"));
        assert!(is_valid_db_name("checkpoints"));
        assert!(is_valid_db_name("_private"));
        assert!(!is_valid_db_name(""));
        assert!(!is_valid_db_name("1bad"));
        assert!(!is_valid_db_name("has-dash"));
        assert!(!is_valid_db_name("has space"));
    }
}
