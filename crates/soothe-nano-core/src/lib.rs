//! Core domain models ported from `core/verbosity.py`, `core/registry.py`,
//! `core/events.py`, `core/types.py`, and `core/exceptions.py`.
//!
//! Pure data/logic with no framework coupling. The Python side delegates the
//! pure-logic portions (verbosity checks, domain classification, event type
//! constants, priority enum) here and retains Pydantic models + Pydantic-driven
//! registration on the Python side.

pub mod classification;
pub mod constants;
pub mod priority;
pub mod verbosity;
