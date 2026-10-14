//! Event priority levels for queue overflow management.
//!
//! Higher priority events are processed first and less likely to be dropped
//! when queues are near capacity.

use serde::{Deserialize, Serialize};

/// Event priority for queue overflow management.
///
/// Lower numeric value = higher priority (processed first, less likely dropped).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[repr(u8)]
pub enum EventPriority {
    /// Never dropped, block if necessary.
    Critical = 0,
    /// Rarely drop (tool/subagent results).
    High = 1,
    /// Standard priority (heartbeat, status).
    #[default]
    Normal = 2,
    /// First to drop (debug/trace).
    Low = 3,
}

impl EventPriority {
    /// Return the discriminant value.
    pub const fn as_int(self) -> u8 {
        self as u8
    }

    /// Return the discriminant as `i64`.
    pub const fn to_i64(self) -> i64 {
        self as u8 as i64
    }

    /// Parse a priority from its integer value.
    pub fn from_i64(value: i64) -> Option<Self> {
        match value {
            0 => Some(EventPriority::Critical),
            1 => Some(EventPriority::High),
            2 => Some(EventPriority::Normal),
            3 => Some(EventPriority::Low),
            _ => None,
        }
    }

    /// Return the string name.
    pub const fn name(self) -> &'static str {
        match self {
            EventPriority::Critical => "CRITICAL",
            EventPriority::High => "HIGH",
            EventPriority::Normal => "NORMAL",
            EventPriority::Low => "LOW",
        }
    }

    /// Default priority (Normal).
    pub const fn default_value() -> Self {
        EventPriority::Normal
    }
}

/// Parse a priority from its integer value.
pub fn from_int(value: u8) -> Option<EventPriority> {
    match value {
        0 => Some(EventPriority::Critical),
        1 => Some(EventPriority::High),
        2 => Some(EventPriority::Normal),
        3 => Some(EventPriority::Low),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn priority_values_match_python() {
        assert_eq!(EventPriority::Critical.as_int(), 0);
        assert_eq!(EventPriority::High.as_int(), 1);
        assert_eq!(EventPriority::Normal.as_int(), 2);
        assert_eq!(EventPriority::Low.as_int(), 3);
    }

    #[test]
    fn default_is_normal() {
        assert_eq!(EventPriority::default(), EventPriority::Normal);
        assert_eq!(EventPriority::default_value(), EventPriority::Normal);
    }

    #[test]
    fn from_int_roundtrip() {
        for p in [
            EventPriority::Critical,
            EventPriority::High,
            EventPriority::Normal,
            EventPriority::Low,
        ] {
            assert_eq!(from_int(p.as_int()), Some(p));
        }
        assert_eq!(from_int(99), None);
    }

    #[test]
    fn serde_roundtrip() {
        let p = EventPriority::Critical;
        let json = serde_json::to_string(&p).unwrap();
        let back: EventPriority = serde_json::from_str(&json).unwrap();
        assert_eq!(back, EventPriority::Critical);
    }
}
