//! PyO3 bindings for `soothe_nano_utils::subagents`.
//!
//! Exposes pure-logic subagent helpers (topic stripping, search-query compaction,
//! effort parsing, report summaries, reference formatting, termination logic)
//! to Python as `soothe_nano._rust.subagents_*`.

#![allow(clippy::type_complexity, clippy::too_many_arguments)]

use pyo3::prelude::*;
use soothe_nano_utils::subagents as sa;

// ── Topic attachment stripping ─────────────────────────────────────────────

#[pyfunction]
fn subagents_ui_language_suffix(py: Python<'_>, topic: &str) -> String {
    py.allow_threads(|| sa::ui_language_suffix(topic))
}

#[pyfunction]
fn subagents_topic_without_attachments(py: Python<'_>, topic: &str) -> String {
    py.allow_threads(|| sa::topic_without_attachments(topic))
}

#[pyfunction]
fn subagents_planned_research_topic(
    py: Python<'_>,
    parsed: PyObject,
    raw_topic: &str,
) -> PyResult<String> {
    // Convert PyObject to serde_json::Value via Python json.dumps
    let json_str: String = if parsed.is_none(py) {
        String::new()
    } else {
        let json_mod = py.import_bound("json")?;
        let dumped: Bound<'_, PyAny> = json_mod.call_method("dumps", (parsed,), None)?;
        dumped.extract()?
    };
    let parsed_value: Option<serde_json::Value> =
        if json_str.is_empty() {
            None
        } else {
            Some(serde_json::from_str(&json_str).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("Invalid JSON: {e}"))
            })?)
        };
    let result = py.allow_threads(|| sa::planned_research_topic(parsed_value.as_ref(), raw_topic));
    Ok(result)
}

// ── Search query compaction ────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (raw, max_len=120))]
fn subagents_compact_search_query(py: Python<'_>, raw: &str, max_len: usize) -> String {
    py.allow_threads(|| sa::compact_search_query(raw, max_len))
}

#[pyfunction]
fn subagents_fallback_sub_questions(py: Python<'_>, topic: &str) -> Vec<PyObject> {
    let result = py.allow_threads(|| sa::fallback_sub_questions(topic));
    result
        .into_iter()
        .map(|v| {
            let json_str = serde_json::to_string(&v).unwrap_or_else(|_| "null".to_string());
            let json_mod = py.import_bound("json").unwrap();
            json_mod
                .call_method("loads", (json_str,), None)
                .unwrap()
                .into()
        })
        .collect()
}

#[pyfunction]
fn subagents_fallback_queries(
    py: Python<'_>,
    topic: &str,
    sub_questions: Vec<PyObject>,
) -> Vec<PyObject> {
    // Convert each PyObject to serde_json::Value
    let json_mod = py.import_bound("json").unwrap();
    let sq_values: Vec<serde_json::Value> = sub_questions
        .iter()
        .map(|obj| {
            let dumped: String = json_mod
                .call_method("dumps", (obj,), None)
                .unwrap()
                .extract()
                .unwrap();
            serde_json::from_str(&dumped).unwrap_or(serde_json::Value::Null)
        })
        .collect();
    let result = py.allow_threads(|| sa::fallback_queries(topic, Some(&sq_values)));
    result
        .into_iter()
        .map(|v| {
            let json_str = serde_json::to_string(&v).unwrap_or_else(|_| "null".to_string());
            json_mod
                .call_method("loads", (json_str,), None)
                .unwrap()
                .into()
        })
        .collect()
}

// ── Effort parsing ─────────────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (raw=None))]
fn subagents_normalize_effort(py: Python<'_>, raw: Option<&str>) -> String {
    py.allow_threads(|| sa::normalize_effort(raw))
}

#[pyfunction]
fn subagents_parse_effort_from_text(py: Python<'_>, text: &str) -> Option<String> {
    py.allow_threads(|| sa::parse_effort_from_text(text))
}

#[pyfunction]
fn subagents_profile_for_effort(py: Python<'_>, effort: &str) -> (String, i64, i64, i64, i64, i64) {
    py.allow_threads(|| {
        let p = sa::profile_for_effort(effort);
        (
            p.effort,
            p.max_sub_questions,
            p.max_initial_queries,
            p.max_follow_up_queries,
            p.max_loops,
            p.crawl_top_n,
        )
    })
}

#[pyfunction]
fn subagents_effort_plan_hint(py: Python<'_>, effort: &str) -> String {
    py.allow_threads(|| sa::profile_for_effort(effort).plan_hint())
}

#[pyfunction]
fn subagents_effort_follow_up_hint(py: Python<'_>, effort: &str) -> String {
    py.allow_threads(|| sa::profile_for_effort(effort).reflect_follow_up_hint())
}

// ── Preview ────────────────────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (text, chars=200))]
fn subagents_preview_first(py: Python<'_>, text: &str, chars: usize) -> String {
    py.allow_threads(|| sa::preview_first(text, chars))
}

// ── Result summary ─────────────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (result, max_len=160))]
fn subagents_result_summary_for_display(py: Python<'_>, result: &str, max_len: usize) -> String {
    py.allow_threads(|| sa::result_summary_for_display(result, max_len))
}

// ── Report display summary ─────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (report, topic, fallback_prefix))]
fn subagents_derive_report_title(
    py: Python<'_>,
    report: &str,
    topic: &str,
    fallback_prefix: &str,
) -> String {
    py.allow_threads(|| sa::derive_report_title(report, topic, fallback_prefix))
}

#[pyfunction]
#[pyo3(signature = (report, preferred_sections, max_len=320))]
fn subagents_brief_summary_for_display(
    py: Python<'_>,
    report: &str,
    preferred_sections: Vec<String>,
    max_len: usize,
) -> String {
    let sections_refs: Vec<&str> = preferred_sections.iter().map(|s| s.as_str()).collect();
    py.allow_threads(|| sa::brief_summary_for_display(report, &sections_refs, max_len))
}

// ── Reference key/merge/format ────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (url, source_name, source_ref))]
fn subagents_reference_key(
    py: Python<'_>,
    url: Option<&str>,
    source_name: &str,
    source_ref: &str,
) -> String {
    py.allow_threads(|| sa::reference_key(url, source_name, source_ref))
}

/// Parse a list of Python dicts (ResearchReference-like) into Rust tuples.
fn parse_ref_list(
    py: Python<'_>,
    refs: &[PyObject],
) -> PyResult<Vec<(Option<String>, String, String, String, Option<String>)>> {
    let json_mod = py.import_bound("json")?;
    let mut parsed_refs = Vec::new();
    for obj in refs {
        let dumped: String = json_mod.call_method("dumps", (obj,), None)?.extract()?;
        let val: serde_json::Value =
            serde_json::from_str(&dumped).unwrap_or(serde_json::Value::Null);
        let empty = serde_json::Map::new();
        let obj_map = val.as_object().unwrap_or(&empty);
        let url = obj_map
            .get("url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let source_name = obj_map
            .get("source_name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let source_ref = obj_map
            .get("source_ref")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let title = obj_map
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let query = obj_map
            .get("query")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        parsed_refs.push((url, source_name, source_ref, title, query));
    }
    Ok(parsed_refs)
}

#[pyfunction]
#[pyo3(signature = (refs, accessed_date=None))]
fn subagents_format_references_section(
    py: Python<'_>,
    refs: Vec<PyObject>,
    accessed_date: Option<&str>,
) -> PyResult<String> {
    let parsed_refs = parse_ref_list(py, &refs)?;
    let result = py.allow_threads(|| sa::format_references_section(&parsed_refs, accessed_date));
    Ok(result)
}

#[pyfunction]
fn subagents_merge_reference_indices(py: Python<'_>, refs: Vec<PyObject>) -> PyResult<Vec<usize>> {
    let parsed_refs = parse_ref_list(py, &refs)?;
    let result = py.allow_threads(|| sa::merge_reference_indices(&parsed_refs));
    Ok(result)
}

// ── Loop termination ──────────────────────────────────────────────────────

/// PyO3 wrapper for TerminationDecision.
#[pyclass(name = "TerminationDecision", module = "soothe_nano._rust")]
#[derive(Clone)]
pub struct PyTerminationDecision {
    pub should_terminate: bool,
    pub reason: String,
    pub confidence: f64,
}

#[pymethods]
impl PyTerminationDecision {
    #[new]
    fn new(should_terminate: bool, reason: String, confidence: f64) -> Self {
        Self {
            should_terminate,
            reason,
            confidence,
        }
    }

    #[getter]
    fn should_terminate(&self) -> bool {
        self.should_terminate
    }

    #[getter]
    fn reason(&self) -> String {
        self.reason.clone()
    }

    #[getter]
    fn confidence(&self) -> f64 {
        self.confidence
    }

    fn __repr__(&self) -> String {
        format!(
            "TerminationDecision(should_terminate={}, reason='{}', confidence={})",
            self.should_terminate, self.reason, self.confidence
        )
    }
}

#[pyfunction]
#[pyo3(signature = (min_results, min_source_diversity, max_duplicate_ratio, min_content_length, accumulated_source_names, current_contents, current_source_names, iteration))]
fn subagents_check_termination(
    py: Python<'_>,
    min_results: usize,
    min_source_diversity: usize,
    max_duplicate_ratio: f64,
    min_content_length: usize,
    accumulated_source_names: Vec<String>,
    current_contents: Vec<String>,
    current_source_names: Vec<String>,
    iteration: usize,
) -> PyTerminationDecision {
    let config = sa::TerminationConfig {
        min_results,
        min_source_diversity,
        max_duplicate_ratio,
        min_content_length,
    };
    let current_results: Vec<sa::SourceResultInfo> = current_contents
        .into_iter()
        .zip(current_source_names.into_iter())
        .map(|(content, source_name)| sa::SourceResultInfo {
            content,
            source_name,
        })
        .collect();
    let decision = py.allow_threads(|| {
        sa::check_termination(
            &config,
            &accumulated_source_names,
            &current_results,
            iteration,
        )
    });
    PyTerminationDecision {
        should_terminate: decision.should_terminate,
        reason: decision.reason,
        confidence: decision.confidence,
    }
}

// ── Scenario fallback classification ───────────────────────────────────────

#[pyfunction]
fn subagents_academic_fallback_classification(
    py: Python<'_>,
    topic: &str,
) -> (String, Vec<String>, Vec<String>) {
    py.allow_threads(|| sa::academic_fallback_classification(topic))
}

#[pyfunction]
fn subagents_deep_fallback_classification(
    py: Python<'_>,
    topic: &str,
) -> (String, Vec<String>, Vec<String>) {
    py.allow_threads(|| sa::deep_fallback_classification(topic))
}

// ── JSON parsing ──────────────────────────────────────────────────────────

#[pyfunction]
fn subagents_parse_json_from_llm(py: Python<'_>, content: &str) -> PyResult<PyObject> {
    let result = py.allow_threads(|| sa::parse_json_from_llm(content));
    match result {
        Some(value) => {
            let json_str = serde_json::to_string(&value)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let json_mod = py.import_bound("json")?;
            let result = json_mod.call_method("loads", (json_str,), None)?;
            Ok(result.into())
        }
        None => Ok(py.None()),
    }
}

// ── Timeout ────────────────────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (configured, wizsearch_timeout, slack_sec=5.0))]
fn subagents_effective_source_timeout(
    py: Python<'_>,
    configured: f64,
    wizsearch_timeout: f64,
    slack_sec: f64,
) -> f64 {
    py.allow_threads(|| sa::effective_source_timeout(configured, wizsearch_timeout, slack_sec))
}

#[pyfunction]
fn subagents_default_wizsearch_timeout() -> f64 {
    sa::default_wizsearch_timeout()
}

// ── Registration ───────────────────────────────────────────────────────────

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(subagents_ui_language_suffix, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_topic_without_attachments, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_planned_research_topic, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_compact_search_query, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_fallback_sub_questions, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_fallback_queries, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_normalize_effort, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_parse_effort_from_text, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_profile_for_effort, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_effort_plan_hint, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_effort_follow_up_hint, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_preview_first, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_result_summary_for_display, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_derive_report_title, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_brief_summary_for_display, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_reference_key, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_format_references_section, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_merge_reference_indices, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_check_termination, m)?)?;
    m.add_function(wrap_pyfunction!(
        subagents_academic_fallback_classification,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(subagents_deep_fallback_classification, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_parse_json_from_llm, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_effective_source_timeout, m)?)?;
    m.add_function(wrap_pyfunction!(subagents_default_wizsearch_timeout, m)?)?;
    m.add_class::<PyTerminationDecision>()?;
    Ok(())
}
