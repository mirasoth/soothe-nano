//! PyO3 bindings for `soothe-nano-core`.
//!
//! Exposes the pure-logic core models (verbosity tiers, event priorities,
//! domain classification, event type constants) to Python.

use pyo3::prelude::*;
use soothe_nano_core::{classification, constants, priority, verbosity};

// ── VerbosityTier ──────────────────────────────────────────────

/// Visibility class for catalog events.
///
/// `NORMAL` (1) events are sent to clients; `INTERNAL` (99) events are not.
#[pyclass(name = "VerbosityTier", module = "soothe_nano._rust")]
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct PyVerbosityTier {
    inner: verbosity::VerbosityTier,
}

#[pymethods]
impl PyVerbosityTier {
    #[new]
    fn new(value: i64) -> PyResult<Self> {
        verbosity::VerbosityTier::from_i64(value)
            .map(|inner| Self { inner })
            .ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "{value} is not a valid VerbosityTier"
                ))
            })
    }

    /// Integer value (1 for NORMAL, 99 for INTERNAL).
    #[getter]
    fn value(&self) -> i64 {
        self.inner.to_i64()
    }

    /// String name (``"NORMAL"`` or ``"INTERNAL"``).
    #[getter]
    fn name(&self) -> String {
        self.inner.name().to_string()
    }

    fn __repr__(&self) -> String {
        format!(
            "<VerbosityTier.{}: {}>",
            self.inner.name(),
            self.inner.to_i64()
        )
    }

    fn __str__(&self) -> String {
        self.inner.name().to_string()
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    fn __hash__(&self) -> u64 {
        self.inner.to_i64() as u64
    }

    fn __int__(&self) -> i64 {
        self.inner.to_i64()
    }

    /// ``NORMAL`` singleton.
    #[classattr]
    #[allow(non_snake_case)]
    fn NORMAL() -> Self {
        Self {
            inner: verbosity::VerbosityTier::Normal,
        }
    }

    /// ``INTERNAL`` singleton.
    #[classattr]
    #[allow(non_snake_case)]
    fn INTERNAL() -> Self {
        Self {
            inner: verbosity::VerbosityTier::Internal,
        }
    }
}

impl From<verbosity::VerbosityTier> for PyVerbosityTier {
    fn from(inner: verbosity::VerbosityTier) -> Self {
        Self { inner }
    }
}

// ── EventPriority ──────────────────────────────────────────────

/// Event priority levels for queue overflow management.
///
/// Lower integer = higher priority. ``CRITICAL`` events are never dropped.
#[pyclass(name = "EventPriority", module = "soothe_nano._rust")]
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct PyEventPriority {
    inner: priority::EventPriority,
}

#[pymethods]
impl PyEventPriority {
    #[new]
    fn new(value: i64) -> PyResult<Self> {
        priority::EventPriority::from_i64(value)
            .map(|inner| Self { inner })
            .ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "{value} is not a valid EventPriority"
                ))
            })
    }

    #[getter]
    fn value(&self) -> i64 {
        self.inner.to_i64()
    }

    #[getter]
    fn name(&self) -> String {
        self.inner.name().to_string()
    }

    fn __repr__(&self) -> String {
        format!(
            "<EventPriority.{}: {}>",
            self.inner.name(),
            self.inner.to_i64()
        )
    }

    fn __str__(&self) -> String {
        self.inner.name().to_string()
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    fn __hash__(&self) -> u64 {
        self.inner.to_i64() as u64
    }

    fn __int__(&self) -> i64 {
        self.inner.to_i64()
    }

    #[classattr]
    #[allow(non_snake_case)]
    fn CRITICAL() -> Self {
        Self {
            inner: priority::EventPriority::Critical,
        }
    }

    #[classattr]
    #[allow(non_snake_case)]
    fn HIGH() -> Self {
        Self {
            inner: priority::EventPriority::High,
        }
    }

    #[classattr]
    #[allow(non_snake_case)]
    fn NORMAL() -> Self {
        Self {
            inner: priority::EventPriority::Normal,
        }
    }

    #[classattr]
    #[allow(non_snake_case)]
    fn LOW() -> Self {
        Self {
            inner: priority::EventPriority::Low,
        }
    }
}

impl From<priority::EventPriority> for PyEventPriority {
    fn from(inner: priority::EventPriority) -> Self {
        Self { inner }
    }
}

// ── Free functions ─────────────────────────────────────────────

/// Return True if tier is client-visible (NORMAL).
#[pyfunction]
fn should_show(tier: &PyVerbosityTier) -> bool {
    verbosity::should_show(tier.inner)
}

/// Return the domain from an event type string via split('.')[1].
#[pyfunction]
fn classify_domain(event_type: &str) -> String {
    classification::classify(event_type)
}

/// Return the default verbosity tier for a top-level domain.
#[pyfunction]
fn domain_default_tier(domain: &str) -> PyVerbosityTier {
    classification::domain_default_tier(domain).into()
}

/// Return the verbosity tier for an event type (domain-default fallback).
#[pyfunction]
fn get_verbosity_for_type(event_type: &str) -> PyVerbosityTier {
    classification::get_verbosity(event_type).into()
}

/// Split a type string into (domain, component, action, default_tier).
#[pyfunction]
fn split_domain(py: Python<'_>, type_string: &str) -> (String, String, String, PyVerbosityTier) {
    py.allow_threads(|| {
        let (domain, component, action, tier) = classification::split_domain(type_string);
        (domain, component, action, tier.into())
    })
}

/// Parse a legacy verbosity string alias into a VerbosityTier.
///
/// ``quiet``/``normal`` → NORMAL; ``detailed``/``debug``/``internal`` → INTERNAL;
/// unknown strings default to NORMAL. Matching is case-insensitive.
#[pyfunction]
fn parse_verbosity_alias(alias: &str) -> PyVerbosityTier {
    verbosity::VerbosityTier::from_legacy_str(alias).into()
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyVerbosityTier>()?;
    m.add_class::<PyEventPriority>()?;

    m.add_function(wrap_pyfunction!(should_show, m)?)?;
    m.add_function(wrap_pyfunction!(classify_domain, m)?)?;
    m.add_function(wrap_pyfunction!(domain_default_tier, m)?)?;
    m.add_function(wrap_pyfunction!(get_verbosity_for_type, m)?)?;
    m.add_function(wrap_pyfunction!(split_domain, m)?)?;
    m.add_function(wrap_pyfunction!(parse_verbosity_alias, m)?)?;

    // Event type constants
    m.add("PLAN_CREATED", constants::PLAN_CREATED)?;
    m.add("STRANGE_LOOP_STARTED", constants::STRANGE_LOOP_STARTED)?;
    m.add("STRANGE_LOOP_COMPLETED", constants::STRANGE_LOOP_COMPLETED)?;
    m.add(
        "STRANGE_LOOP_STEP_STARTED",
        constants::STRANGE_LOOP_STEP_STARTED,
    )?;
    m.add(
        "STRANGE_LOOP_STEP_QUEUED",
        constants::STRANGE_LOOP_STEP_QUEUED,
    )?;
    m.add(
        "STRANGE_LOOP_STEP_COMPLETED",
        constants::STRANGE_LOOP_STEP_COMPLETED,
    )?;
    m.add(
        "STRANGE_LOOP_PLAN_DECISION",
        constants::STRANGE_LOOP_PLAN_DECISION,
    )?;
    m.add(
        "STRANGE_LOOP_PLAN_PHASE",
        constants::STRANGE_LOOP_PLAN_PHASE,
    )?;
    m.add("WIRED_SUBAGENT_STARTED", constants::WIRED_SUBAGENT_STARTED)?;
    m.add(
        "WIRED_SUBAGENT_COMPLETED",
        constants::WIRED_SUBAGENT_COMPLETED,
    )?;
    m.add("WIRED_SUBAGENT_FAILED", constants::WIRED_SUBAGENT_FAILED)?;
    m.add(
        "WIRED_SUBAGENT_CANCELLED",
        constants::WIRED_SUBAGENT_CANCELLED,
    )?;
    m.add("INTENT_CLASSIFIED", constants::INTENT_CLASSIFIED)?;
    m.add(
        "LOOP_CLARIFICATION_REQUESTED",
        constants::LOOP_CLARIFICATION_REQUESTED,
    )?;
    m.add(
        "LOOP_CLARIFICATION_ANSWERED",
        constants::LOOP_CLARIFICATION_ANSWERED,
    )?;
    m.add(
        "LOOP_CLARIFICATION_DEFERRED",
        constants::LOOP_CLARIFICATION_DEFERRED,
    )?;
    m.add("STREAM_END", constants::STREAM_END)?;
    m.add("CARD_CREATED", constants::CARD_CREATED)?;
    m.add("CARD_UPDATED", constants::CARD_UPDATED)?;
    m.add("CARD_FINALIZED", constants::CARD_FINALIZED)?;
    m.add("CARD_REPLAY_BEGIN", constants::CARD_REPLAY_BEGIN)?;
    m.add("CARD_REPLAY_END", constants::CARD_REPLAY_END)?;
    m.add("ERROR", constants::ERROR)?;
    m.add("LLM_RETRY_ATTEMPT", constants::LLM_RETRY_ATTEMPT)?;
    m.add("MEMORY_RECALLED", constants::MEMORY_RECALLED)?;
    m.add("MEMORY_STORED", constants::MEMORY_STORED)?;
    m.add("POLICY_CHECKED", constants::POLICY_CHECKED)?;
    m.add("POLICY_DENIED", constants::POLICY_DENIED)?;
    m.add(
        "DEFAULT_STRANGE_LOOP_MAX_ITERATIONS",
        constants::DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    )?;

    Ok(())
}
