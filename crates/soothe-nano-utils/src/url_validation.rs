//! URL validation (ported from `utils/url_validation.py`).

use thiserror::Error;

#[derive(Debug, Error)]
pub enum UrlValidationError {
    #[error("empty URL")]
    Empty,
    #[error("invalid scheme: expected http or https, got {0}")]
    InvalidScheme(String),
    #[error("missing host")]
    MissingHost,
    #[error("URL parse error: {0}")]
    ParseError(String),
}

/// A validated HTTP(S) URL.
#[derive(Debug, Clone)]
pub struct ValidatedUrl {
    pub scheme: String,
    pub host: String,
    pub port: Option<u16>,
    pub path: String,
}

/// Validate that a URL string is well-formed and uses http/https.
pub fn validate_url(raw: &str) -> Result<ValidatedUrl, UrlValidationError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(UrlValidationError::Empty);
    }

    let (scheme, rest) = trimmed
        .split_once("://")
        .ok_or_else(|| UrlValidationError::ParseError("no scheme separator".into()))?;

    let scheme_lower = scheme.to_lowercase();
    if scheme_lower != "http" && scheme_lower != "https" {
        return Err(UrlValidationError::InvalidScheme(scheme.to_string()));
    }

    let (authority, path) = rest.split_once('/').unwrap_or((rest, ""));
    let (host, port_str) = authority
        .split_once(':')
        .map(|(h, p)| (h, Some(p)))
        .unwrap_or((authority, None));

    if host.is_empty() {
        return Err(UrlValidationError::MissingHost);
    }

    let port = port_str
        .map(|s| {
            s.parse::<u16>()
                .map_err(|e| UrlValidationError::ParseError(e.to_string()))
        })
        .transpose()?;

    Ok(ValidatedUrl {
        scheme: scheme_lower,
        host: host.to_string(),
        port,
        path: format!("/{path}"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_https() {
        let u = validate_url("https://example.com/path").unwrap();
        assert_eq!(u.scheme, "https");
        assert_eq!(u.host, "example.com");
        assert_eq!(u.path, "/path");
    }

    #[test]
    fn valid_http_with_port() {
        let u = validate_url("http://localhost:8080").unwrap();
        assert_eq!(u.port, Some(8080));
    }

    #[test]
    fn rejects_ftp() {
        assert!(matches!(
            validate_url("ftp://example.com"),
            Err(UrlValidationError::InvalidScheme(_))
        ));
    }

    #[test]
    fn rejects_empty() {
        assert!(matches!(validate_url(""), Err(UrlValidationError::Empty)));
    }
}
