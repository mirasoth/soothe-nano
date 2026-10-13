//! Circuit breaker state machine.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

/// Breaker state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitState {
    Closed,
    Open,
    HalfOpen,
}

/// Token-bucket / sliding-window circuit breaker.
pub struct CircuitBreaker {
    failure_threshold: u64,
    recovery_timeout: Duration,
    failures: AtomicU64,
    last_failure: std::sync::Mutex<Option<Instant>>,
}

impl CircuitBreaker {
    pub fn new(failure_threshold: u64, recovery_timeout: Duration) -> Self {
        Self {
            failure_threshold,
            recovery_timeout,
            failures: AtomicU64::new(0),
            last_failure: std::sync::Mutex::new(None),
        }
    }

    pub fn state(&self) -> CircuitState {
        let failures = self.failures.load(Ordering::Relaxed);
        if failures < self.failure_threshold {
            return CircuitState::Closed;
        }
        let guard = self.last_failure.lock().unwrap();
        match *guard {
            Some(t) if t.elapsed() >= self.recovery_timeout => CircuitState::HalfOpen,
            _ => CircuitState::Open,
        }
    }

    pub fn record_success(&self) {
        self.failures.store(0, Ordering::Relaxed);
        *self.last_failure.lock().unwrap() = None;
    }

    pub fn record_failure(&self) {
        self.failures.fetch_add(1, Ordering::Relaxed);
        *self.last_failure.lock().unwrap() = Some(Instant::now());
    }

    pub fn allow_request(&self) -> bool {
        match self.state() {
            CircuitState::Closed | CircuitState::HalfOpen => true,
            CircuitState::Open => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closed_then_open_then_half_open() {
        let cb = CircuitBreaker::new(3, Duration::from_millis(50));
        assert_eq!(cb.state(), CircuitState::Closed);
        cb.record_failure();
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Closed);
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        std::thread::sleep(Duration::from_millis(60));
        assert_eq!(cb.state(), CircuitState::HalfOpen);
        cb.record_success();
        assert_eq!(cb.state(), CircuitState::Closed);
    }
}
