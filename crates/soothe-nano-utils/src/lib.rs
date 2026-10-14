//! Pure-logic utilities ported from `utils/*.py`.

pub mod chrome_detect;
pub mod circuit_breaker;
pub mod content_chars;
pub mod env_resolve;
pub mod error_simplify;
pub mod event_format;
pub mod formatting;
pub mod json_parsing;
pub mod langfuse_names;
pub mod logging_fmt;
pub mod output_capture;
pub mod path;
pub mod prompt_clock;
pub mod subagents;
pub mod task_namespace;
pub mod text_preview;
pub mod thread_id;
pub mod thread_id_suffix;
pub mod url_validation;

pub use circuit_breaker::{CircuitBreaker, CircuitState};
pub use formatting::{convert_and_abbreviate_path, format_cli_error, log_preview};
pub use json_parsing::repair_json;
pub use output_capture::OutputCapture;
pub use path::normalize_relative;
pub use task_namespace::ParsedUnifiedToolCallId;
pub use text_preview::{preview_full, text_preview};
pub use thread_id::generate_thread_id;
pub use url_validation::{validate_url, UrlValidationError};

// Re-export new pure-logic helpers.
pub use chrome_detect::{
    exe_name_is_chrome_like, extract_debug_port, extract_exe_path_from_args, extract_user_data_dir,
    is_chrome_like_process, parse_singleton_owner_pid,
};
pub use content_chars::{coerce_total_tokens_used, count_str_chars};
pub use env_resolve::{
    normalize_tags, resolve_env_vars, resolve_env_vars_os, resolve_str, resolve_str_os,
};
pub use error_simplify::{
    is_llm_argument_error, is_unexpected_keyword_error, is_warning_level_error,
    missing_required_count, simplify_error, unexpected_kwarg_name,
};
pub use event_format::format_event_compact;
pub use langfuse_names::{
    execute_step_langfuse_run_display_name, loop_graph_langfuse_run_display_name,
};
pub use thread_id_suffix::short_thread_id_for_log;
