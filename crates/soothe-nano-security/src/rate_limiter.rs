//! Rate limiter (ported from security rate limiting logic).

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Instant;

/// Token bucket rate limiter (fast-path, per-key).
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

/// Sliding-window rate limiter (mirrors the Python `RateLimiter` in
/// `security_enforcer.py` — records operation timestamps and checks
/// counts within a rolling window).
pub struct SlidingWindowRateLimiter {
    window_seconds: f64,
    operations: Mutex<HashMap<String, Vec<f64>>>,
    path_operations: Mutex<HashMap<String, Vec<f64>>>,
}

impl SlidingWindowRateLimiter {
    pub fn new(window_seconds: u64) -> Self {
        Self {
            window_seconds: window_seconds as f64,
            operations: Mutex::new(HashMap::new()),
            path_operations: Mutex::new(HashMap::new()),
        }
    }

    /// Current monotonic time in seconds (epoch-like, for window math).
    fn now() -> f64 {
        let dur = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        dur.as_secs_f64()
    }

    /// Record an operation for a path.
    pub fn record(&self, operation: &str, path: &str) {
        let now = Self::now();
        let cutoff = now - self.window_seconds;
        {
            let mut ops = self.operations.lock().unwrap();
            let times = ops.entry(operation.to_string()).or_default();
            times.retain(|t| *t > cutoff);
            times.push(now);
        }
        {
            let mut pops = self.path_operations.lock().unwrap();
            let times = pops.entry(path.to_string()).or_default();
            times.retain(|t| *t > cutoff);
            times.push(now);
        }
    }

    /// Check the rate for an operation (optionally per-path).
    /// Returns `(allowed, count)`.
    pub fn check_rate(
        &self,
        operation: &str,
        max_count: usize,
        path: Option<&str>,
    ) -> (bool, usize) {
        let now = Self::now();
        let cutoff = now - self.window_seconds;
        if let Some(path) = path {
            let mut pops = self.path_operations.lock().unwrap();
            let times = pops.entry(path.to_string()).or_default();
            times.retain(|t| *t > cutoff);
            let count = times.len();
            if count >= max_count {
                return (false, count);
            }
            (true, count)
        } else {
            let mut ops = self.operations.lock().unwrap();
            let times = ops.entry(operation.to_string()).or_default();
            times.retain(|t| *t > cutoff);
            let count = times.len();
            if count >= max_count {
                return (false, count);
            }
            (true, count)
        }
    }

    /// Return stats: per-operation and per-path counts within the window.
    pub fn get_stats(&self) -> HashMap<String, HashMap<String, usize>> {
        let now = Self::now();
        let cutoff = now - self.window_seconds;
        let mut result: HashMap<String, HashMap<String, usize>> = HashMap::new();

        let ops = self.operations.lock().unwrap();
        let mut op_stats: HashMap<String, usize> = HashMap::new();
        for (op, times) in ops.iter() {
            let count = times.iter().filter(|t| **t > cutoff).count();
            op_stats.insert(op.clone(), count);
        }
        result.insert("operations".to_string(), op_stats);

        let pops = self.path_operations.lock().unwrap();
        let mut path_stats: HashMap<String, usize> = HashMap::new();
        for (path, times) in pops.iter() {
            let count = times.iter().filter(|t| **t > cutoff).count();
            path_stats.insert(path.clone(), count);
        }
        result.insert("paths".to_string(), path_stats);

        result
    }
}

impl Default for SlidingWindowRateLimiter {
    fn default() -> Self {
        Self::new(60)
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

    #[test]
    fn sliding_window_allows_within_limit() {
        let rl = SlidingWindowRateLimiter::new(60);
        let (allowed, _count) = rl.check_rate("read", 5, None);
        assert!(allowed);
    }

    #[test]
    fn sliding_window_records_and_checks() {
        let rl = SlidingWindowRateLimiter::new(60);
        rl.record("read", "/tmp/file1");
        rl.record("read", "/tmp/file1");
        rl.record("read", "/tmp/file1");
        let (allowed, count) = rl.check_rate("read", 3, Some("/tmp/file1"));
        assert!(!allowed);
        assert_eq!(count, 3);
    }

    #[test]
    fn sliding_window_per_path_independent() {
        let rl = SlidingWindowRateLimiter::new(60);
        rl.record("read", "/tmp/file1");
        let (allowed, count) = rl.check_rate("read", 1, Some("/tmp/file2"));
        assert!(allowed);
        assert_eq!(count, 0);
    }

    #[test]
    fn sliding_window_stats_nonempty_after_record() {
        let rl = SlidingWindowRateLimiter::new(60);
        rl.record("read", "/tmp/file1");
        let stats = rl.get_stats();
        assert!(stats.contains_key("operations"));
        assert!(stats.contains_key("paths"));
        let op_stats = stats.get("operations").unwrap();
        assert_eq!(op_stats.get("read"), Some(&1));
    }

    #[test]
    fn sliding_window_default_is_60s() {
        let rl = SlidingWindowRateLimiter::default();
        assert_eq!(rl.window_seconds, 60.0);
    }
}
