//! Skill budget tracking (ported from `skills/budget.py`).

use std::sync::atomic::{AtomicU32, Ordering};

/// Atomic budget tracker for skill token usage.
pub struct SkillBudget {
    remaining: AtomicU32,
}

impl SkillBudget {
    pub fn new(initial: u32) -> Self {
        Self {
            remaining: AtomicU32::new(initial),
        }
    }

    /// Try to spend `tokens` from the budget. Returns true if allowed.
    pub fn spend(&self, tokens: u32) -> bool {
        let mut current = self.remaining.load(Ordering::Relaxed);
        loop {
            if current < tokens {
                return false;
            }
            match self.remaining.compare_exchange_weak(
                current,
                current - tokens,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => return true,
                Err(actual) => current = actual,
            }
        }
    }

    /// Remaining budget.
    pub fn remaining(&self) -> u32 {
        self.remaining.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spend_within_budget() {
        let budget = SkillBudget::new(100);
        assert!(budget.spend(30));
        assert_eq!(budget.remaining(), 70);
    }

    #[test]
    fn spend_exceeds_budget() {
        let budget = SkillBudget::new(50);
        assert!(budget.spend(50));
        assert!(!budget.spend(1));
    }
}
