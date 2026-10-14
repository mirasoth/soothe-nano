//! IdentityProtocol data models — AKSK authentication and JWT token management.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Token type values.
pub const TOKEN_TYPES: &[&str] = &["access", "refresh"];

/// True when `token_type` is a valid token type.
pub fn is_valid_token_type(token_type: &str) -> bool {
    TOKEN_TYPES.contains(&token_type)
}

/// Soothe user identity.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub user_id: String,
    pub created_at: String,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl User {
    pub fn new(user_id: String, created_at: String) -> Self {
        Self {
            user_id,
            created_at,
            metadata: HashMap::new(),
        }
    }
}

/// Access Key / Secret Key credential pair.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AKSKPair {
    pub aksk_id: String,
    pub user_id: String,
    pub access_key: String,
    pub secret_key_hash: String,
    pub created_at: String,
    #[serde(default)]
    pub expires_at: Option<String>,
    #[serde(default)]
    pub revoked: bool,
    #[serde(default)]
    pub revoked_at: Option<String>,
}

impl AKSKPair {
    pub fn new(
        aksk_id: String,
        user_id: String,
        access_key: String,
        secret_key_hash: String,
        created_at: String,
    ) -> Self {
        Self {
            aksk_id,
            user_id,
            access_key,
            secret_key_hash,
            created_at,
            expires_at: None,
            revoked: false,
            revoked_at: None,
        }
    }

    /// True when the AKSK pair is revoked.
    pub fn is_revoked(&self) -> bool {
        self.revoked
    }

    /// True when the AKSK pair has expired (expires_at < now_iso).
    /// Returns false when expires_at is None (never expires).
    pub fn is_expired(&self, now_iso: &str) -> bool {
        match &self.expires_at {
            Some(exp) => exp.as_str() < now_iso,
            None => false,
        }
    }

    /// True when the AKSK pair is active (not revoked and not expired).
    pub fn is_active(&self, now_iso: &str) -> bool {
        !self.is_revoked() && !self.is_expired(now_iso)
    }
}

/// JWT token claims.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenClaims {
    pub jti: String,
    pub user_id: String,
    pub aksk_id: String,
    pub token_type: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl TokenClaims {
    pub fn new(
        jti: String,
        user_id: String,
        aksk_id: String,
        token_type: String,
        issued_at: String,
        expires_at: String,
    ) -> Self {
        Self {
            jti,
            user_id,
            aksk_id,
            token_type,
            issued_at,
            expires_at,
        }
    }

    /// True when the token is expired (expires_at < now_iso).
    pub fn is_expired(&self, now_iso: &str) -> bool {
        self.expires_at.as_str() < now_iso
    }

    /// True when the token is an access token.
    pub fn is_access(&self) -> bool {
        self.token_type == "access"
    }

    /// True when the token is a refresh token.
    pub fn is_refresh(&self) -> bool {
        self.token_type == "refresh"
    }
}

/// External channel identity mapping.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalIdentityMapping {
    pub mapping_id: String,
    pub channel: String,
    pub sender_id: String,
    pub user_id: String,
    pub created_at: String,
}

impl ExternalIdentityMapping {
    pub fn new(
        mapping_id: String,
        channel: String,
        sender_id: String,
        user_id: String,
        created_at: String,
    ) -> Self {
        Self {
            mapping_id,
            channel,
            sender_id,
            user_id,
            created_at,
        }
    }
}

/// Authentication result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthResult {
    pub access_token: String,
    pub refresh_token: String,
    pub user_id: String,
    pub expires_in: i64,
}

impl AuthResult {
    pub fn new(
        access_token: String,
        refresh_token: String,
        user_id: String,
        expires_in: i64,
    ) -> Self {
        Self {
            access_token,
            refresh_token,
            user_id,
            expires_in,
        }
    }
}

/// Token refresh result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenRefreshResult {
    pub access_token: String,
    pub refresh_token: String,
    pub expires_in: i64,
}

impl TokenRefreshResult {
    pub fn new(access_token: String, refresh_token: String, expires_in: i64) -> Self {
        Self {
            access_token,
            refresh_token,
            expires_in,
        }
    }
}

/// Token info for listing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenInfo {
    pub jti: String,
    pub user_id: String,
    pub aksk_id: String,
    pub token_type: String,
    pub issued_at: String,
    pub expires_at: String,
    pub revoked: bool,
}

impl TokenInfo {
    pub fn new(
        jti: String,
        user_id: String,
        aksk_id: String,
        token_type: String,
        issued_at: String,
        expires_at: String,
    ) -> Self {
        Self {
            jti,
            user_id,
            aksk_id,
            token_type,
            issued_at,
            expires_at,
            revoked: false,
        }
    }

    /// True when the token is revoked.
    pub fn is_revoked(&self) -> bool {
        self.revoked
    }

    /// True when the token is expired (expires_at < now_iso).
    pub fn is_expired(&self, now_iso: &str) -> bool {
        self.expires_at.as_str() < now_iso
    }

    /// True when the token is active (not revoked and not expired).
    pub fn is_active(&self, now_iso: &str) -> bool {
        !self.is_revoked() && !self.is_expired(now_iso)
    }
}

/// Service status.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdentityStatus {
    pub enabled: bool,
    pub storage_backend: String,
    pub jwt_key_source: String,
    pub users_count: i64,
    pub active_aksk_count: i64,
    pub active_tokens_count: i64,
}

impl IdentityStatus {
    pub fn new(
        enabled: bool,
        storage_backend: String,
        jwt_key_source: String,
        users_count: i64,
        active_aksk_count: i64,
        active_tokens_count: i64,
    ) -> Self {
        Self {
            enabled,
            storage_backend,
            jwt_key_source,
            users_count,
            active_aksk_count,
            active_tokens_count,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aksk_active() {
        let pair = AKSKPair::new(
            "id1".into(),
            "user1".into(),
            "AK-xxx".into(),
            "hash".into(),
            "2024-01-01T00:00:00Z".into(),
        );
        assert!(!pair.is_revoked());
        assert!(pair.is_active("2024-06-01T00:00:00Z"));
    }

    #[test]
    fn aksk_revoked() {
        let mut pair = AKSKPair::new(
            "id1".into(),
            "user1".into(),
            "AK-xxx".into(),
            "hash".into(),
            "2024-01-01T00:00:00Z".into(),
        );
        pair.revoked = true;
        assert!(!pair.is_active("2024-06-01T00:00:00Z"));
    }

    #[test]
    fn aksk_expired() {
        let mut pair = AKSKPair::new(
            "id1".into(),
            "user1".into(),
            "AK-xxx".into(),
            "hash".into(),
            "2024-01-01T00:00:00Z".into(),
        );
        pair.expires_at = Some("2024-03-01T00:00:00Z".into());
        assert!(pair.is_expired("2024-06-01T00:00:00Z"));
        assert!(!pair.is_active("2024-06-01T00:00:00Z"));
        assert!(pair.is_active("2024-02-01T00:00:00Z"));
    }

    #[test]
    fn token_claims_types() {
        let access = TokenClaims::new(
            "jti1".into(),
            "u1".into(),
            "ak1".into(),
            "access".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-12-01T00:00:00Z".into(),
        );
        assert!(access.is_access());
        assert!(!access.is_refresh());
        assert!(!access.is_expired("2024-06-01T00:00:00Z"));
        assert!(access.is_expired("2025-06-01T00:00:00Z"));
    }

    #[test]
    fn token_info_active() {
        let ti = TokenInfo::new(
            "jti1".into(),
            "u1".into(),
            "ak1".into(),
            "access".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-12-01T00:00:00Z".into(),
        );
        assert!(ti.is_active("2024-06-01T00:00:00Z"));
        assert!(!ti.is_active("2025-06-01T00:00:00Z"));
    }

    #[test]
    fn valid_token_types() {
        assert!(is_valid_token_type("access"));
        assert!(is_valid_token_type("refresh"));
        assert!(!is_valid_token_type("bogus"));
    }

    #[test]
    fn roundtrip_user() {
        let u = User::new("u1".into(), "2024-01-01T00:00:00Z".into());
        let s = serde_json::to_string(&u).unwrap();
        let back: User = serde_json::from_str(&s).unwrap();
        assert_eq!(back.user_id, "u1");
    }

    #[test]
    fn roundtrip_auth_result() {
        let a = AuthResult::new("at".into(), "rt".into(), "u1".into(), 3600);
        let s = serde_json::to_string(&a).unwrap();
        let back: AuthResult = serde_json::from_str(&s).unwrap();
        assert_eq!(back.expires_in, 3600);
    }
}
