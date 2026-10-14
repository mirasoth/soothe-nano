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
    pub query: Option<String>,
    pub fragment: Option<String>,
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

    // Split off fragment first (if any).
    let (rest, fragment) = match rest.split_once('#') {
        Some((r, f)) => (r, Some(f.to_string())),
        None => (rest, None),
    };

    // Split off query (if any).
    let (rest, query) = match rest.split_once('?') {
        Some((r, q)) => (r, Some(q.to_string())),
        None => (rest, None),
    };

    // Now rest is authority + path.
    let (authority, path) = rest
        .split_once('/')
        .map(|(a, p)| (a, format!("/{p}")))
        .unwrap_or((rest, String::new()));

    // Strip userinfo (user:pass@host) if present.
    let authority = match authority.rsplit_once('@') {
        Some((_, host_part)) => host_part,
        None => authority,
    };

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
        path,
        query,
        fragment,
    })
}

/// Reconstruct the sanitized URL string.
impl ValidatedUrl {
    pub fn to_url_string(&self) -> String {
        let path = if self.path.is_empty() {
            "/"
        } else {
            &self.path
        };
        let mut url = format!(
            "{}://{}{}{}",
            self.scheme,
            self.host,
            self.port.map(|p| format!(":{p}")).unwrap_or_default(),
            path
        );
        if let Some(ref q) = self.query {
            url.push('?');
            url.push_str(q);
        }
        if let Some(ref f) = self.fragment {
            url.push('#');
            url.push_str(f);
        }
        url
    }
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
        assert!(u.query.is_none());
        assert!(u.fragment.is_none());
    }

    #[test]
    fn valid_http_with_port() {
        let u = validate_url("http://localhost:8080").unwrap();
        assert_eq!(u.port, Some(8080));
    }

    #[test]
    fn preserves_query_string() {
        let u = validate_url("https://example.com/path?key=value&foo=bar").unwrap();
        assert_eq!(u.query.as_deref(), Some("key=value&foo=bar"));
        assert_eq!(
            u.to_url_string(),
            "https://example.com/path?key=value&foo=bar"
        );
    }

    #[test]
    fn preserves_fragment() {
        let u = validate_url("https://example.com/path#section").unwrap();
        assert_eq!(u.fragment.as_deref(), Some("section"));
        assert_eq!(u.to_url_string(), "https://example.com/path#section");
    }

    #[test]
    fn preserves_query_and_fragment() {
        let u = validate_url("https://example.com/search?q=hello#top").unwrap();
        assert_eq!(u.query.as_deref(), Some("q=hello"));
        assert_eq!(u.fragment.as_deref(), Some("top"));
        assert_eq!(u.to_url_string(), "https://example.com/search?q=hello#top");
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

    #[test]
    fn empty_path_gets_slash() {
        let u = validate_url("https://example.com").unwrap();
        assert_eq!(u.path, "");
        assert_eq!(u.to_url_string(), "https://example.com/");
    }

    #[test]
    fn strips_userinfo() {
        let u = validate_url("https://user:pass@example.com/path").unwrap();
        assert_eq!(u.host, "example.com");
        assert_eq!(u.to_url_string(), "https://example.com/path");
    }

    #[test]
    fn userinfo_with_port() {
        let u = validate_url("https://user:pass@example.com:8080/path").unwrap();
        assert_eq!(u.host, "example.com");
        assert_eq!(u.port, Some(8080));
        assert_eq!(u.to_url_string(), "https://example.com:8080/path");
    }
}
