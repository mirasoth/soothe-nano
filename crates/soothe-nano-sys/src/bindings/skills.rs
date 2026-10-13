//! PyO3 bindings for `soothe-nano-skills`.
//!
//! Exposes `SkillDiscovery` (filesystem scan for .md skill files),
//! `CorpusMatcher` (cosine similarity search over embeddings), and
//! `SkillBudget` (atomic token budget tracker) as Python classes.

use pyo3::prelude::*;
use soothe_nano_skills::{CorpusMatcher, SkillBudget, SkillDiscovery};

// ── SkillDiscovery ────────────────────────────────────────────

#[pyclass(name = "SkillDiscovery")]
pub struct PySkillDiscovery {
    inner: SkillDiscovery,
}

#[pymethods]
impl PySkillDiscovery {
    #[new]
    fn new(roots: Vec<String>) -> Self {
        let roots: Vec<_> = roots.into_iter().map(std::path::PathBuf::from).collect();
        Self {
            inner: SkillDiscovery::new(roots),
        }
    }

    /// Discover all skills across all roots. Returns list of (name, path, description) tuples.
    fn discover(&self) -> Vec<(String, String, String)> {
        self.inner
            .discover()
            .into_iter()
            .map(|e| (e.name, e.path, e.description))
            .collect()
    }
}

// ── CorpusMatcher ─────────────────────────────────────────────

#[pyclass(name = "CorpusMatcher")]
pub struct PyCorpusMatcher {
    inner: CorpusMatcher,
}

#[pymethods]
impl PyCorpusMatcher {
    /// Create from a flattened embedding matrix (n_skills × dims).
    #[new]
    fn new(embeddings: Vec<f32>, dims: usize) -> Self {
        Self {
            inner: CorpusMatcher::new(embeddings, dims),
        }
    }

    /// Number of skills in the corpus.
    #[getter]
    fn len(&self) -> usize {
        self.inner.len()
    }

    /// Search for the top-k most similar skills to `query` embedding.
    /// Returns list of (score, index) tuples sorted by descending score.
    fn cosine_search(&self, query: Vec<f32>, top_k: usize) -> Vec<(f32, usize)> {
        self.inner.cosine_search(&query, top_k)
    }
}

// ── SkillBudget ───────────────────────────────────────────────

#[pyclass(name = "SkillBudget")]
pub struct PySkillBudget {
    inner: SkillBudget,
}

#[pymethods]
impl PySkillBudget {
    #[new]
    fn new(initial: u32) -> Self {
        Self {
            inner: SkillBudget::new(initial),
        }
    }

    /// Try to spend `tokens` from the budget. Returns True if allowed.
    fn spend(&self, tokens: u32) -> bool {
        self.inner.spend(tokens)
    }

    /// Remaining budget.
    #[getter]
    fn remaining(&self) -> u32 {
        self.inner.remaining()
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySkillDiscovery>()?;
    m.add_class::<PyCorpusMatcher>()?;
    m.add_class::<PySkillBudget>()?;
    Ok(())
}
