//! Path utilities.

use std::path::{Path, PathBuf};

/// Normalize a relative path: strip leading `./`, collapse `..`/`.`,
/// and reject absolute paths.
pub fn normalize_relative(input: &str) -> Result<PathBuf, String> {
    let p = Path::new(input);
    if p.is_absolute() {
        return Err(format!("absolute paths not allowed: {input}"));
    }
    let mut out = PathBuf::new();
    for component in p.components() {
        use std::path::Component;
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    return Err(format!("path escapes root: {input}"));
                }
            }
            Component::Normal(seg) => out.push(seg),
            Component::RootDir | Component::Prefix(_) => {
                return Err(format!("absolute paths not allowed: {input}"));
            }
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normal_relative() {
        let p = normalize_relative("a/b/c").unwrap();
        assert_eq!(p, PathBuf::from("a/b/c"));
    }

    #[test]
    fn collapses_dotdot() {
        let p = normalize_relative("a/../b").unwrap();
        assert_eq!(p, PathBuf::from("b"));
    }

    #[test]
    fn rejects_absolute() {
        assert!(normalize_relative("/etc/passwd").is_err());
    }

    #[test]
    fn rejects_escape() {
        assert!(normalize_relative("../../escape").is_err());
    }
}
