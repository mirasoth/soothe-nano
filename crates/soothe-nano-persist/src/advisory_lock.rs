//! Advisory lock key generation (ported from `db_init/runner.py`).

use sha2::{Digest, Sha256};

/// Compute a stable 63-bit advisory lock key from a database name.
///
/// Mirrors `int.from_bytes(sha256(name.encode()).digest()[:8], 'big') & 0x7FFF_FFFF_FFFF_FFFF`.
pub fn advisory_lock_key(database: &str) -> i64 {
    let mut hasher = Sha256::new();
    hasher.update(database.as_bytes());
    let digest = hasher.finalize();
    let bytes: [u8; 8] = digest[..8].try_into().expect("digest has at least 8 bytes");
    let val = i64::from_be_bytes(bytes);
    val & 0x7FFF_FFFF_FFFF_FFFF
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_key_is_stable() {
        let k1 = advisory_lock_key("soothe_metadata");
        let k2 = advisory_lock_key("soothe_metadata");
        assert_eq!(k1, k2);
    }

    #[test]
    fn test_different_names_yield_different_keys() {
        let k1 = advisory_lock_key("soothe_metadata");
        let k2 = advisory_lock_key("soothe_checkpoints");
        assert_ne!(k1, k2);
    }

    #[test]
    fn test_key_is_positive() {
        let k = advisory_lock_key("soothe_vectors");
        assert!(k >= 0);
    }
}
