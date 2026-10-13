//! Corpus matching — cosine similarity over pre-computed skill embeddings
//! (ported from `skills/corpus_match.py`).

/// Cosine similarity corpus matcher.
pub struct CorpusMatcher {
    embeddings: Vec<f32>,
    dims: usize,
}

impl CorpusMatcher {
    /// Create from a flattened embedding matrix (n_skills × dims).
    pub fn new(embeddings: Vec<f32>, dims: usize) -> Self {
        Self { embeddings, dims }
    }

    /// Number of skills in the corpus.
    pub fn len(&self) -> usize {
        self.embeddings.len().checked_div(self.dims).unwrap_or(0)
    }

    /// Check if the corpus is empty.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Search for the top-k most similar skills to `query` embedding.
    pub fn cosine_search(&self, query: &[f32], top_k: usize) -> Vec<(f32, usize)> {
        let n = self.len();
        let mut scores: Vec<(f32, usize)> = (0..n)
            .map(|i| {
                let embedding = &self.embeddings[i * self.dims..(i + 1) * self.dims];
                (cosine(query, embedding), i)
            })
            .collect();
        scores.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        scores.truncate(top_k);
        scores
    }
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot / (norm_a * norm_b)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cosine_search_finds_best() {
        // 3 skills, 2 dims
        let embeddings = vec![1.0, 0.0, 0.0, 1.0, 1.0, 1.0];
        let matcher = CorpusMatcher::new(embeddings, 2);
        let query = vec![1.0, 0.0];
        let results = matcher.cosine_search(&query, 1);
        assert_eq!(results[0].1, 0); // first skill is exact match
        assert!((results[0].0 - 1.0).abs() < 1e-6);
    }
}
