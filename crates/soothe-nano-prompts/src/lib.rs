//! System prompt templates and context XML assembly.
//!
//! Ports: `prompts/system_templates.py`, `prompts/context_xml.py`,
//! `prompts/identity.py`, `prompts/project_instructions.py`.

pub mod context_xml;
pub mod identity;
pub mod project_instructions;
pub mod system_templates;

pub use context_xml::build_context_xml;
pub use identity::IDENTITY;
pub use project_instructions::load_project_instructions;
pub use system_templates::build_system_prompt;
