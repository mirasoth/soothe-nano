//! Vector math operations (ported from `backends/vector_store/sqlite_vec.py`).
//!
//! Math is done in `f64` internally to match Python's `float` (double) precision,
//! even though inputs are `f32` (the storage format used by sqlite-vec).

/// Pack a list of floats into F32 binary format for sqlite-vec (little-endian).
pub fn pack_vector_f32(vector: &[f32]) -> Vec<u8> {
    let mut buf = Vec::with_capacity(vector.len() * 4);
    for &v in vector {
        buf.extend_from_slice(&v.to_le_bytes());
    }
    buf
}

/// Compute cosine similarity between two vectors.
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f64 {
    let dot: f64 = a
        .iter()
        .zip(b.iter())
        .map(|(x, y)| (*x as f64) * (*y as f64))
        .sum();
    let norm_a: f64 = a
        .iter()
        .map(|x| (*x as f64) * (*x as f64))
        .sum::<f64>()
        .sqrt();
    let norm_b: f64 = b
        .iter()
        .map(|x| (*x as f64) * (*x as f64))
        .sum::<f64>()
        .sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

/// Compute L2 (Euclidean) distance between two vectors.
pub fn l2_distance(a: &[f32], b: &[f32]) -> f64 {
    let sum: f64 = a
        .iter()
        .zip(b.iter())
        .map(|(x, y)| {
            let d = *x as f64 - *y as f64;
            d * d
        })
        .sum();
    sum.sqrt()
}

/// Compute inner product (dot product) similarity.
pub fn ip_similarity(a: &[f32], b: &[f32]) -> f64 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (*x as f64) * (*y as f64))
        .sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cosine_similarity_orthogonal() {
        assert!((cosine_similarity(&[1.0, 0.0], &[0.0, 1.0])).abs() < 1e-12);
    }

    #[test]
    fn test_cosine_similarity_identical() {
        let sim = cosine_similarity(&[1.0, 2.0, 3.0], &[1.0, 2.0, 3.0]);
        assert!((sim - 1.0).abs() < 1e-12);
    }

    #[test]
    fn test_cosine_similarity_zero_vector() {
        assert_eq!(cosine_similarity(&[0.0, 0.0], &[1.0, 1.0]), 0.0);
    }

    #[test]
    fn test_l2_distance() {
        let d = l2_distance(&[0.0, 0.0], &[3.0, 4.0]);
        assert!((d - 5.0).abs() < 1e-12);
    }

    #[test]
    fn test_l2_distance_sqrt2() {
        let d = l2_distance(&[1.0, 0.0, 0.0], &[0.0, 1.0, 0.0]);
        assert!((d - 2.0_f64.sqrt()).abs() < 1e-12);
    }

    #[test]
    fn test_ip_similarity() {
        let s = ip_similarity(&[1.0, 2.0, 3.0], &[4.0, 5.0, 6.0]);
        assert!((s - 32.0).abs() < 1e-12);
    }

    #[test]
    fn test_pack_vector_f32() {
        let packed = pack_vector_f32(&[1.0, 0.0]);
        assert_eq!(packed.len(), 8);
    }
}
