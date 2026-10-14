//! Budgeted skill-listing formatter (ported from `skills/budget.py`).

/// A skill entry to format.
#[derive(Debug, Clone)]
pub struct SkillEntry {
    pub name: String,
    pub description: String,
    pub when_to_use: String,
    /// `"builtin"` or other source label.
    pub source: String,
}

/// Outcome of a budgeted listing: counts, mode, and char usage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BudgetTelemetry {
    pub included_count: usize,
    pub truncated_count: usize,
    /// `"full"` | `"truncated"` | `"names_only"`
    pub mode: &'static str,
    pub budget_chars: usize,
    pub actual_chars: usize,
}

fn is_builtin(e: &SkillEntry) -> bool {
    e.source == "builtin"
}

/// Format a single entry. `cap=None` renders full; `cap=Some(n)` truncates.
fn format_entry(e: &SkillEntry, cap: Option<usize>) -> String {
    let name = &e.name;
    let mut desc = e.description.clone();
    if let Some(c) = cap {
        if desc.chars().count() > c {
            let keep = c.saturating_sub(1);
            let truncated: String = desc.chars().take(keep).collect();
            desc = format!("{}…", truncated.trim_end());
        }
    }
    let wt = e.when_to_use.trim();
    if !wt.is_empty() {
        if let Some(c) = cap {
            let remaining = c.saturating_sub(desc.chars().count());
            if remaining > 10 {
                let wt_trim: String = wt.chars().take(remaining).collect();
                return format!("- {name}: {desc}\n  When to use: {wt_trim}");
            }
        } else {
            return format!("- {name}: {desc}\n  When to use: {wt}");
        }
    }
    format!("- {name}: {desc}")
}

/// Format skill listing within a character budget. Returns `(text, telemetry)`.
pub fn format_skills_within_budget(
    entries: Vec<SkillEntry>,
    budget_chars: usize,
    per_entry_cap_chars: usize,
    min_per_entry_chars: usize,
) -> (String, BudgetTelemetry) {
    if entries.is_empty() {
        return (
            String::new(),
            BudgetTelemetry {
                included_count: 0,
                truncated_count: 0,
                mode: "full",
                budget_chars,
                actual_chars: 0,
            },
        );
    }

    let full_rendered: Vec<String> = entries.iter().map(|e| format_entry(e, None)).collect();
    let total_full: usize = full_rendered.iter().map(|r| r.chars().count() + 1).sum();
    if total_full <= budget_chars {
        let text = full_rendered.join("\n");
        return (
            text.clone(),
            BudgetTelemetry {
                included_count: entries.len(),
                truncated_count: 0,
                mode: "full",
                budget_chars,
                actual_chars: text.chars().count(),
            },
        );
    }

    // Over budget: built-ins keep full description; share remaining among non-builtins.
    let builtins: Vec<&SkillEntry> = entries.iter().filter(|e| is_builtin(e)).collect();
    let others: Vec<&SkillEntry> = entries.iter().filter(|e| !is_builtin(e)).collect();
    let builtin_text = builtins
        .iter()
        .map(|e| format_entry(e, None))
        .collect::<Vec<_>>()
        .join("\n");
    let used = builtin_text.chars().count() + 1;
    let remaining = budget_chars.saturating_sub(used);
    let raw_quota = if others.is_empty() {
        0
    } else {
        remaining / others.len()
    };
    let quota = raw_quota.min(per_entry_cap_chars);

    if quota < min_per_entry_chars && !others.is_empty() {
        // names-only mode for non-builtins
        let names = others
            .iter()
            .map(|e| format!("- {}", e.name))
            .collect::<Vec<_>>()
            .join("\n");
        let text = if builtin_text.is_empty() {
            names
        } else {
            format!("{builtin_text}\n{names}")
        };
        return (
            text.clone(),
            BudgetTelemetry {
                included_count: entries.len(),
                truncated_count: others.len(),
                mode: "names_only",
                budget_chars,
                actual_chars: text.chars().count(),
            },
        );
    }

    let others_text = others
        .iter()
        .map(|e| format_entry(e, Some(quota)))
        .collect::<Vec<_>>()
        .join("\n");
    let text = if builtin_text.is_empty() {
        others_text
    } else if others_text.is_empty() {
        builtin_text
    } else {
        format!("{builtin_text}\n{others_text}")
    };
    let truncated_count = others
        .iter()
        .filter(|e| e.description.chars().count() > quota)
        .count();
    (
        text.clone(),
        BudgetTelemetry {
            included_count: entries.len(),
            truncated_count,
            mode: "truncated",
            budget_chars,
            actual_chars: text.chars().count(),
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(name: &str, description: &str) -> SkillEntry {
        SkillEntry {
            name: name.to_string(),
            description: description.to_string(),
            when_to_use: String::new(),
            source: "user".to_string(),
        }
    }

    fn entry_wt(name: &str, description: &str, when_to_use: &str) -> SkillEntry {
        SkillEntry {
            name: name.to_string(),
            description: description.to_string(),
            when_to_use: when_to_use.to_string(),
            source: "user".to_string(),
        }
    }

    fn builtin(name: &str, description: &str) -> SkillEntry {
        SkillEntry {
            name: name.to_string(),
            description: description.to_string(),
            when_to_use: String::new(),
            source: "builtin".to_string(),
        }
    }

    #[test]
    fn empty_list_returns_empty_full() {
        let (text, tel) = format_skills_within_budget(vec![], 500, 250, 20);
        assert_eq!(text, "");
        assert_eq!(tel.mode, "full");
        assert_eq!(tel.included_count, 0);
        assert_eq!(tel.actual_chars, 0);
    }

    #[test]
    fn under_budget_uses_full_mode() {
        let entries = vec![entry("a", "Alpha skill"), entry("b", "Beta skill")];
        let (text, tel) = format_skills_within_budget(entries, 500, 250, 20);
        assert!(text.contains("a"));
        assert!(text.contains("b"));
        assert_eq!(tel.mode, "full");
        assert_eq!(tel.included_count, 2);
        assert_eq!(tel.truncated_count, 0);
        assert_eq!(tel.actual_chars, text.chars().count());
    }

    #[test]
    fn over_budget_uses_truncated_mode() {
        let entries: Vec<SkillEntry> = (0..20)
            .map(|i| entry(&format!("skill_{i}"), &"Description ".repeat(20)))
            .collect();
        let (text, tel) = format_skills_within_budget(entries, 200, 250, 20);
        assert!(tel.mode == "truncated" || tel.mode == "names_only");
        assert!(tel.included_count > 0);
        assert!(!text.is_empty());
    }

    #[test]
    fn extreme_budget_uses_names_only_mode() {
        let entries = vec![entry("a", "Alpha"), entry("b", "Beta"), entry("c", "Gamma")];
        let (text, tel) = format_skills_within_budget(entries, 10, 250, 100);
        assert_eq!(tel.mode, "names_only");
        assert_eq!(tel.truncated_count, 3);
        assert!(text.contains("- a"));
        assert!(text.contains("- b"));
        assert!(text.contains("- c"));
    }

    #[test]
    fn when_to_use_included_in_full_mode() {
        let entries = vec![entry_wt("a", "Alpha skill", "Use for Python files")];
        let (text, _tel) = format_skills_within_budget(entries, 500, 250, 20);
        assert!(text.contains("Python"));
        assert!(text.contains("When to use"));
    }

    #[test]
    fn per_entry_cap_truncates_description() {
        let long_desc = "A".repeat(500);
        let entries = vec![entry("a", &long_desc), entry("b", &"B".repeat(500))];
        let (text, tel) = format_skills_within_budget(entries, 100, 50, 20);
        assert!(tel.mode == "truncated" || tel.mode == "names_only");
        assert!(!text.contains(&long_desc));
    }

    #[test]
    fn builtins_keep_full_descriptions_in_truncated_mode() {
        // Builtin description is short; non-builtin is long enough that the
        // full render exceeds the budget, but the builtin's reserved space
        // still leaves a per-entry quota >= min for the non-builtin.
        let entries = vec![
            builtin("core", "Core builtin skill"),
            entry("extra", &"X".repeat(300)),
        ];
        // Full render ~336 chars; budget 150 forces truncated mode. Builtin
        // render ~25 chars, leaving ~124 for one non-builtin -> quota 50
        // (capped) which is >= min 20 -> truncated, not names_only.
        let (text, tel) = format_skills_within_budget(entries, 150, 50, 20);
        assert_eq!(tel.mode, "truncated");
        // builtin keeps full description (not truncated to the cap)
        assert!(text.contains("Core builtin skill"));
    }

    #[test]
    fn truncated_count_counts_oversized_others() {
        let entries = vec![entry("a", &"A".repeat(100)), entry("b", &"B".repeat(100))];
        let (_text, tel) = format_skills_within_budget(entries, 200, 50, 20);
        assert_eq!(tel.mode, "truncated");
        assert_eq!(tel.truncated_count, 2);
    }
}
