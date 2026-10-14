//! Context XML builder.

/// File info for context XML.
#[derive(Debug, Clone)]
pub struct FileInfo {
    pub path: String,
    pub size: u64,
    pub lines: usize,
}

/// Build context XML from workspace path and file list.
pub fn build_context_xml(workspace: &str, files: &[FileInfo]) -> String {
    let mut xml = String::from("<context>\n");
    xml.push_str(&format!(
        "  <workspace>{}</workspace>\n",
        escape_xml(workspace)
    ));
    xml.push_str("  <files>\n");
    for f in files {
        xml.push_str(&format!(
            "    <file path=\"{}\" size=\"{}\" lines=\"{}\"/>\n",
            escape_xml(&f.path),
            f.size,
            f.lines
        ));
    }
    xml.push_str("  </files>\n");
    xml.push_str("</context>");
    xml
}

fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_xml() {
        let files = vec![FileInfo {
            path: "src/main.rs".into(),
            size: 1024,
            lines: 50,
        }];
        let xml = build_context_xml("/tmp/ws", &files);
        assert!(xml.contains("<workspace>/tmp/ws</workspace>"));
        assert!(xml.contains("path=\"src/main.rs\""));
    }

    #[test]
    fn escapes_special_chars() {
        let xml = build_context_xml("<weird>&path", &[]);
        assert!(xml.contains("&lt;weird&gt;&amp;path"));
    }
}
