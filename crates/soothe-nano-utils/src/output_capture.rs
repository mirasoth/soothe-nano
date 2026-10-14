//! stdout/stderr capture and truncation.

/// Truncate output to a max byte length, appending an ellipsis indicator.
pub fn truncate_output(output: &str, max_bytes: usize) -> String {
    if output.len() <= max_bytes {
        return output.to_string();
    }
    let mut end = max_bytes;
    while !output.is_char_boundary(end) {
        end -= 1;
    }
    let truncated = &output[..end];
    format!(
        "{truncated}\n... [output truncated, {} bytes total]",
        output.len()
    )
}

/// Capture container for combined stdout/stderr.
pub struct OutputCapture {
    stdout: String,
    stderr: String,
}

impl OutputCapture {
    pub fn new() -> Self {
        Self {
            stdout: String::new(),
            stderr: String::new(),
        }
    }

    pub fn push_stdout(&mut self, s: &str) {
        self.stdout.push_str(s);
    }

    pub fn push_stderr(&mut self, s: &str) {
        self.stderr.push_str(s);
    }

    pub fn stdout(&self) -> &str {
        &self.stdout
    }

    pub fn stderr(&self) -> &str {
        &self.stderr
    }

    pub fn combined(&self) -> String {
        let mut out = String::with_capacity(self.stdout.len() + self.stderr.len());
        if !self.stdout.is_empty() {
            out.push_str(&self.stdout);
        }
        if !self.stderr.is_empty() {
            if !out.is_empty() {
                out.push('\n');
            }
            out.push_str(&self.stderr);
        }
        out
    }

    pub fn truncated(self, max_bytes: usize) -> (String, String) {
        (
            truncate_output(&self.stdout, max_bytes),
            truncate_output(&self.stderr, max_bytes),
        )
    }
}

impl Default for OutputCapture {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_preserves_char_boundary() {
        let big = "x".repeat(200);
        let out = truncate_output(&big, 100);
        assert!(out.starts_with(&"x".repeat(100)));
        assert!(out.contains("truncated"));
    }

    #[test]
    fn no_truncation_when_small() {
        let out = truncate_output("hello", 100);
        assert_eq!(out, "hello");
    }
}
