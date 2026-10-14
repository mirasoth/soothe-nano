//! Environment variable expansion.

/// Expand `${VAR}` and `$VAR` patterns in a string.
pub fn expand_env_vars(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let chars: Vec<char> = input.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '$' && i + 1 < chars.len() {
            if chars[i + 1] == '{' {
                if let Some(end) = chars[i + 2..].iter().position(|&c| c == '}') {
                    let var_name: String = chars[i + 2..i + 2 + end].iter().collect();
                    match std::env::var(&var_name) {
                        Ok(val) => result.push_str(&val),
                        Err(_) => {
                            let original: String = chars[i..i + 2 + end + 1].iter().collect();
                            result.push_str(&original);
                        }
                    }
                    i = i + 2 + end + 1;
                    continue;
                }
            } else if chars[i + 1].is_ascii_alphabetic() || chars[i + 1] == '_' {
                let start = i + 1;
                let mut end = start;
                while end < chars.len() && (chars[end].is_ascii_alphanumeric() || chars[end] == '_')
                {
                    end += 1;
                }
                let var_name: String = chars[start..end].iter().collect();
                match std::env::var(&var_name) {
                    Ok(val) => result.push_str(&val),
                    Err(_) => {
                        let original: String = chars[i..end].iter().collect();
                        result.push_str(&original);
                    }
                }
                i = end;
                continue;
            }
        }
        result.push(chars[i]);
        i += 1;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expand_brace_form() {
        std::env::set_var("TEST_VAR", "hello");
        assert_eq!(expand_env_vars("${TEST_VAR}/world"), "hello/world");
        std::env::remove_var("TEST_VAR");
    }

    #[test]
    fn expand_plain_form() {
        std::env::set_var("HOME", "/users/test");
        assert_eq!(expand_env_vars("$HOME/.soothe"), "/users/test/.soothe");
        std::env::remove_var("HOME");
    }

    #[test]
    fn no_expansion_for_literal() {
        assert_eq!(expand_env_vars("plain text"), "plain text");
    }

    #[test]
    fn unset_var_left_unchanged() {
        std::env::remove_var("UNSET_VAR_XYZ");
        assert_eq!(
            expand_env_vars("${UNSET_VAR_XYZ}/path"),
            "${UNSET_VAR_XYZ}/path"
        );
        assert_eq!(
            expand_env_vars("$UNSET_VAR_XYZ/path"),
            "$UNSET_VAR_XYZ/path"
        );
    }
}
