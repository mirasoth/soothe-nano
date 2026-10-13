//! Pure-logic utilities ported from `utils/*.py`.

pub mod circuit_breaker;
pub mod json_parsing;
pub mod output_capture;
pub mod path;
pub mod text_preview;
pub mod thread_id;
pub mod url_validation;

pub use circuit_breaker::{CircuitBreaker, CircuitState};
pub use json_parsing::repair_json;
pub use output_capture::OutputCapture;
pub use path::normalize_relative;
pub use text_preview::{preview_full, text_preview};
pub use thread_id::generate_thread_id;
pub use url_validation::{validate_url, UrlValidationError};
