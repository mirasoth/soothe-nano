//! Environment variable resolution.

use regex::Regex;
use std::sync::OnceLock;

static ENV_REF: OnceLock<Regex> = OnceLock::new();
static ENV_VAR: OnceLock<Regex> = OnceLock::new();

fn env_ref_re() -> &'static Regex {
    ENV_REF.get_or_init(|| Regex::new(r"^\$\{(\w+)\}$").expect("valid regex"))
}

fn env_var_re() -> &'static Regex {
    ENV_VAR.get_or_init(|| Regex::new(r"\$\{(\w+)\}").expect("valid regex"))
}

/// Resolve `${ENV_VAR}` placeholders in a string using the provided lookup function.
///
/// Unresolved placeholders are left as-is.
pub fn resolve_env_vars<F>(value: &str, lookup: F) -> String
where
    F: Fn(&str) -> Option<String>,
{
    env_var_re()
        .replace_all(value, |caps: &regex::Captures| {
            let var_name = &caps[1];
            match lookup(var_name) {
                Some(resolved) => resolved,
                None => caps[0].to_string(),
            }
        })
        .to_string()
}

/// Resolve `${ENV_VAR}` placeholders using the process environment.
pub fn resolve_env_vars_os(value: &str) -> String {
    resolve_env_vars(value, |name| std::env::var(name).ok())
}

/// Resolve a config string: strip whitespace, resolve `${ENV}` placeholders.
///
/// Returns `None` if the value is empty, whitespace-only, or consists solely
/// of an unresolved `${VAR}` reference.
pub fn resolve_str<F>(value: Option<&str>, lookup: F) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    let value = value?;
    let s = value.trim();
    if s.is_empty() {
        return None;
    }
    let out = resolve_env_vars(s, &lookup);
    if env_ref_re().is_match(&out) {
        return None;
    }
    if out.trim().is_empty() {
        return None;
    }
    Some(out)
}

/// Resolve a config string using the process environment.
pub fn resolve_str_os(value: Option<&str>) -> Option<String> {
    resolve_str(value, |name| std::env::var(name).ok())
}

/// Normalize a list of tags to non-empty stripped strings.
///
/// Returns `None` if the input is empty or all tags are empty after stripping.
pub fn normalize_tags(raw: Option<&[String]>) -> Option<Vec<String>> {
    let raw = raw?;
    let out: Vec<String> = raw
        .iter()
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
        .collect();
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_env_vars() {
        let lookup = |name: &str| match name {
            "FOO" => Some("bar".to_string()),
            _ => None,
        };
        assert_eq!(resolve_env_vars("hello ${FOO}", lookup), "hello bar");
        assert_eq!(resolve_env_vars("${FOO}/${BAZ}", lookup), "bar/${BAZ}");
    }

    #[test]
    fn test_resolve_str_none_cases() {
        let lookup = |_: &str| None::<String>;
        assert_eq!(resolve_str(None, lookup), None);
        assert_eq!(resolve_str(Some(""), lookup), None);
        assert_eq!(resolve_str(Some("  "), lookup), None);
    }

    #[test]
    fn test_resolve_str_unresolved_env_ref() {
        let lookup = |_: &str| None::<String>;
        assert_eq!(resolve_str(Some("${UNRESOLVED}"), lookup), None);
    }

    #[test]
    fn test_resolve_str_plain_value() {
        let lookup = |_: &str| None::<String>;
        assert_eq!(
            resolve_str(Some("plain_value"), lookup),
            Some("plain_value".to_string())
        );
    }

    #[test]
    fn test_resolve_str_with_resolved_env() {
        let lookup = |name: &str| match name {
            "KEY" => Some("secret123".to_string()),
            _ => None,
        };
        assert_eq!(
            resolve_str(Some("  ${KEY}  "), lookup),
            Some("secret123".to_string())
        );
    }

    #[test]
    fn test_normalize_tags() {
        assert_eq!(normalize_tags(None), None);
        assert_eq!(normalize_tags(Some(&[])), None);
        assert_eq!(
            normalize_tags(Some(&[
                "  prod ".to_string(),
                "".to_string(),
                "v2".to_string()
            ])),
            Some(vec!["prod".to_string(), "v2".to_string()])
        );
    }
}
