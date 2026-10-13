//! System prompt assembly (ported from `prompts/system_templates.py`).

use soothe_nano_config::SootheConfig;

/// Interaction mode for the agent.
#[derive(Debug, Clone, Copy)]
pub enum InteractionMode {
    Brainstorm,
    Implementation,
    Review,
    Workflow,
}

/// Build the full system prompt from config + mode.
pub fn build_system_prompt(config: &SootheConfig, mode: InteractionMode) -> String {
    let mode_str = match mode {
        InteractionMode::Brainstorm => "brainstorm",
        InteractionMode::Implementation => "implementation",
        InteractionMode::Review => "review",
        InteractionMode::Workflow => "workflow",
    };

    let model = config.resolve_model("default").unwrap_or("unknown");

    format!(
        "{identity}\n\n## Mode\nYou are in **{mode_str}** mode.\n\n## Model\n{model}",
        identity = crate::identity::IDENTITY,
        mode_str = mode_str,
        model = model,
    )
}
