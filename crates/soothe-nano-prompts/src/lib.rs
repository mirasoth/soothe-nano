//! System prompt templates and context XML assembly.

pub mod context_xml;
pub mod environment;
pub mod identity;
pub mod project_instructions;
pub mod system_templates;

pub use context_xml::build_context_xml;
pub use environment::{build_environment_section, build_workspace_section};
pub use identity::IDENTITY;
pub use project_instructions::load_project_instructions;
pub use system_templates::build_system_prompt;
