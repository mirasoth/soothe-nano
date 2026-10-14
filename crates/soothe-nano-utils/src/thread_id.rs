//! Thread ID generation.

use uuid::Uuid;

/// Generate a new UUID v4 thread ID.
pub fn generate_thread_id() -> String {
    Uuid::new_v4().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generates_valid_uuid() {
        let id = generate_thread_id();
        assert!(Uuid::parse_str(&id).is_ok());
    }

    #[test]
    fn unique() {
        let a = generate_thread_id();
        let b = generate_thread_id();
        assert_ne!(a, b);
    }
}
