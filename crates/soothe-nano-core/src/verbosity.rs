//! Verbosity tiers — ported from `core/verbosity.py`.
//!
//! Events classify to one of two tiers:
//! - `Normal`: client-visible — flows over the wire to subscribed clients.
//! - `Internal`: hidden — daemon-side only, never leaves the daemon.

use serde::{Deserialize, Serialize};

/// Visibility class for catalog events.
///
/// `Normal` events are sent to clients; `Internal` events are not.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[repr(u8)]
pub enum VerbosityTier {
    /// Client-visible.
    Normal = 1,
    /// Hidden — daemon-side only.
    Internal = 99,
}

impl VerbosityTier {
    /// Return the discriminant value (matches the Python `IntEnum` value).
    pub const fn as_int(self) -> u8 {
        self as u8
    }

    /// Return the discriminant as `i64` (for PyO3 interop).
    pub const fn to_i64(self) -> i64 {
        self as u8 as i64
    }

    /// Parse a tier from its integer value.
    pub fn from_i64(value: i64) -> Option<Self> {
        match value {
            1 => Some(VerbosityTier::Normal),
            99 => Some(VerbosityTier::Internal),
            _ => None,
        }
    }

    /// Return the string name (matches the Python `IntEnum` member name).
    pub const fn name(self) -> &'static str {
        match self {
            VerbosityTier::Normal => "NORMAL",
            VerbosityTier::Internal => "INTERNAL",
        }
    }

    /// Return True if tier is client-visible.
    pub fn should_show(self) -> bool {
        self == VerbosityTier::Normal
    }

    /// Parse a legacy string alias into a tier.
    ///
    /// `quiet`/`normal` → Normal; `detailed`/`debug`/`internal` → Internal.
    /// Unknown strings default to Normal (matching the Python fallback).
    pub fn from_legacy_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "quiet" | "normal" => VerbosityTier::Normal,
            "detailed" | "debug" | "internal" => VerbosityTier::Internal,
            _ => VerbosityTier::Normal,
        }
    }
}

/// Return True if tier is client-visible.
///
/// Mirrors the module-level `should_show(tier)` function in `verbosity.py`.
pub fn should_show(tier: VerbosityTier) -> bool {
    tier.should_show()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tier_values_match_python() {
        assert_eq!(VerbosityTier::Normal.as_int(), 1);
        assert_eq!(VerbosityTier::Internal.as_int(), 99);
    }

    #[test]
    fn normal_is_visible() {
        assert!(should_show(VerbosityTier::Normal));
        assert!(VerbosityTier::Normal.should_show());
    }

    #[test]
    fn internal_is_hidden() {
        assert!(!should_show(VerbosityTier::Internal));
        assert!(!VerbosityTier::Internal.should_show());
    }

    #[test]
    fn legacy_str_parsing() {
        assert_eq!(
            VerbosityTier::from_legacy_str("quiet"),
            VerbosityTier::Normal
        );
        assert_eq!(
            VerbosityTier::from_legacy_str("normal"),
            VerbosityTier::Normal
        );
        assert_eq!(
            VerbosityTier::from_legacy_str("detailed"),
            VerbosityTier::Internal
        );
        assert_eq!(
            VerbosityTier::from_legacy_str("debug"),
            VerbosityTier::Internal
        );
        assert_eq!(
            VerbosityTier::from_legacy_str("internal"),
            VerbosityTier::Internal
        );
    }

    #[test]
    fn legacy_str_unknown_defaults_to_normal() {
        assert_eq!(
            VerbosityTier::from_legacy_str("bogus"),
            VerbosityTier::Normal
        );
    }

    #[test]
    fn legacy_str_case_insensitive() {
        assert_eq!(
            VerbosityTier::from_legacy_str("DEBUG"),
            VerbosityTier::Internal
        );
        assert_eq!(
            VerbosityTier::from_legacy_str("Normal"),
            VerbosityTier::Normal
        );
    }

    #[test]
    fn serde_roundtrip() {
        let tier = VerbosityTier::Internal;
        let json = serde_json::to_string(&tier).unwrap();
        let back: VerbosityTier = serde_json::from_str(&json).unwrap();
        assert_eq!(back, VerbosityTier::Internal);
    }
}
