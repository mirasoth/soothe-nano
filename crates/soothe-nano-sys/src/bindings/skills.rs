//! PyO3 bindings for `soothe-nano-skills`.

use pyo3::prelude::*;
use soothe_nano_skills::{
    corpus_string, format_skills_within_budget as rs_format_skills, BudgetFormatTelemetry,
    BudgetSkillEntry, CorpusMatcher, SkillBudget, SkillDiscovery,
};

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

    /// Discover all skills across all roots.
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

    /// Top-k most similar skills to `query`. Returns `(score, index)` tuples.
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

    /// Try to spend `tokens` from the budget.
    fn spend(&self, tokens: u32) -> bool {
        self.inner.spend(tokens)
    }

    /// Remaining budget.
    #[getter]
    fn remaining(&self) -> u32 {
        self.inner.remaining()
    }
}

// ── Factory pyfunctions ──────────────────────────────────────

/// Construct a `CorpusMatcher` from a flattened embedding matrix + dims.
#[pyfunction]
fn corpus_matcher_new(embeddings: Vec<f32>, dims: usize) -> PyCorpusMatcher {
    PyCorpusMatcher {
        inner: CorpusMatcher::new(embeddings, dims),
    }
}

/// Construct a `SkillDiscovery` from a list of root directories.
#[pyfunction]
fn skill_discovery_new(roots: Vec<String>) -> PySkillDiscovery {
    let roots: Vec<_> = roots.into_iter().map(std::path::PathBuf::from).collect();
    PySkillDiscovery {
        inner: SkillDiscovery::new(roots),
    }
}

// ── format_skills_within_budget ───────────────────────────────

/// Budgeted skill-listing formatter. Returns `(text, telemetry_dict)`.
#[pyfunction]
#[pyo3(signature = (entries, budget_chars, per_entry_cap_chars=250, min_per_entry_chars=20))]
fn format_skills_within_budget(
    py: Python<'_>,
    entries: Vec<(String, String, String, String)>,
    budget_chars: usize,
    per_entry_cap_chars: usize,
    min_per_entry_chars: usize,
) -> PyResult<(String, PyObject)> {
    let rust_entries: Vec<BudgetSkillEntry> = entries
        .into_iter()
        .map(
            |(name, description, when_to_use, source)| BudgetSkillEntry {
                name,
                description,
                when_to_use,
                source,
            },
        )
        .collect();
    let (text, tel) = py.allow_threads(|| {
        rs_format_skills(
            rust_entries,
            budget_chars,
            per_entry_cap_chars,
            min_per_entry_chars,
        )
    });
    Ok((text, telemetry_to_py(py, tel)))
}

/// Convert `BudgetTelemetry` into a Python dict.
fn telemetry_to_py(py: Python<'_>, tel: BudgetFormatTelemetry) -> PyObject {
    use pyo3::types::PyDict;
    let d = PyDict::new_bound(py);
    let _ = d.set_item("included_count", tel.included_count);
    let _ = d.set_item("truncated_count", tel.truncated_count);
    let _ = d.set_item("mode", tel.mode);
    let _ = d.set_item("budget_chars", tel.budget_chars);
    let _ = d.set_item("actual_chars", tel.actual_chars);
    d.into()
}

// ── corpus_string helpers ─────────────────────────────────────

/// Collapse whitespace, hyphens, and underscores; lowercase.
#[pyfunction]
fn compact(py: Python<'_>, text: &str) -> String {
    py.allow_threads(|| corpus_string::compact(text))
}

/// Find `variant` in `corpus` (word-boundary enforced for short tokens).
#[pyfunction]
fn direct_substring_index(py: Python<'_>, corpus: &str, variant: &str) -> Option<usize> {
    py.allow_threads(|| corpus_string::direct_substring_index(corpus, variant))
}

/// Match `token` against `corpus` after compacting both sides.
/// Returns the original-corpus byte offset or `None`.
#[pyfunction]
fn compact_substring_index(py: Python<'_>, corpus: &str, token: &str) -> Option<usize> {
    py.allow_threads(|| corpus_string::compact_substring_index(corpus, token))
}

/// Map an index in `compact(corpus)` back to an index in `corpus`.
#[pyfunction]
fn compact_index_to_corpus_index(
    py: Python<'_>,
    corpus: &str,
    compact_index: usize,
) -> Option<usize> {
    py.allow_threads(|| corpus_string::compact_index_to_corpus_index(corpus, compact_index))
}

/// Return lowercase variants used when matching a skill name or tag.
#[pyfunction]
#[pyo3(signature = (token, skill_name=None))]
fn match_variants_for_token(py: Python<'_>, token: &str, skill_name: Option<&str>) -> Vec<String> {
    py.allow_threads(|| corpus_string::match_variants_for_token(token, skill_name))
}

/// Return the earliest start index where `token` matches `corpus`, or `None`.
#[pyfunction]
#[pyo3(signature = (corpus, token, skill_name=None))]
fn earliest_corpus_match(
    py: Python<'_>,
    corpus: &str,
    token: &str,
    skill_name: Option<&str>,
) -> Option<usize> {
    py.allow_threads(|| corpus_string::earliest_corpus_match(corpus, token, skill_name))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySkillDiscovery>()?;
    m.add_class::<PyCorpusMatcher>()?;
    m.add_class::<PySkillBudget>()?;
    m.add_function(wrap_pyfunction!(corpus_matcher_new, m)?)?;
    m.add_function(wrap_pyfunction!(skill_discovery_new, m)?)?;
    m.add_function(wrap_pyfunction!(format_skills_within_budget, m)?)?;
    m.add_function(wrap_pyfunction!(compact, m)?)?;
    m.add_function(wrap_pyfunction!(direct_substring_index, m)?)?;
    m.add_function(wrap_pyfunction!(compact_substring_index, m)?)?;
    m.add_function(wrap_pyfunction!(compact_index_to_corpus_index, m)?)?;
    m.add_function(wrap_pyfunction!(match_variants_for_token, m)?)?;
    m.add_function(wrap_pyfunction!(earliest_corpus_match, m)?)?;
    Ok(())
}
