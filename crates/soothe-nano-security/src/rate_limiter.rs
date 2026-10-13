//! Rate limiter (ported from security rate limiting logic).
//!
//! Token bucket per-operation rate limiting.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Instant;

/// Token bucket rate limiter.
pub struct RateLimiter {
    capacity: u32,
    refill_per_minute: u32,
    buckets: Mutex<HashMap<String, Bucket>>,
}

struct Bucket {
    tokens: f64,
    last_refill: Instant,
}

impl RateLimiter {
    pub fn new(capacity: u32, refill_per_minute: u32) -> Self {
        Self {
            capacity,
            refill_per_minute,
            buckets: Mutex::new(HashMap::new()),
        }
    }

    /// Try to consume one token for `key`. Returns true if allowed.
    pub fn try_consume(&self, key: &str) -> bool {
        let mut buckets = self.buckets.lock().unwrap();
        let bucket = buckets.entry(key.to_string()).or_insert(Bucket {
            tokens: self.capacity as f64,
            last_refill: Instant::now(),
        });

        // Refill based on elapsed time
        let elapsed = bucket.last_refill.elapsed();
        let refill = (elapsed.as_secs_f64() / 60.0) * self.refill_per_minute as f64;
        bucket.tokens = (bucket.tokens + refill).min(self.capacity as f64);
        bucket.last_refill = Instant::now();

        if bucket.tokens >= 1.0 {
            bucket.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new(60, 60)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_within_capacity() {
        let rl = RateLimiter::new(5, 60);
        for _ in 0..5 {
            assert!(rl.try_consume("test"));
        }
    }

    #[test]
    fn denies_over_capacity() {
        let rl = RateLimiter::new(2, 0);
        assert!(rl.try_consume("test"));
        assert!(rl.try_consume("test"));
        assert!(!rl.try_consume("test"));
    }
}
