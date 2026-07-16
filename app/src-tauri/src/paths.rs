//! Data root resolution mirroring the core's platformdirs logic.
//!
//! Must resolve to the same directory as the Python side's
//! `platformdirs.user_data_dir("traduko", appauthor=False)` so the app
//! reads the token the core actually wrote.

use std::path::PathBuf;

pub const CORE_PORT: u16 = 8686;
pub const ENV_DATA_ROOT: &str = "TRADUKO_DATA_ROOT";

pub fn resolve_data_root() -> PathBuf {
    if let Ok(explicit) = std::env::var(ENV_DATA_ROOT) {
        if !explicit.is_empty() {
            return PathBuf::from(explicit);
        }
    }
    dirs::data_local_dir()
        .expect("platform data dir unavailable")
        .join("traduko")
}

pub fn read_token(root: &std::path::Path) -> Option<String> {
    std::fs::read_to_string(root.join("config").join("api-token"))
        .ok()
        .map(|raw| raw.trim().to_string())
        .filter(|token| !token.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_env_override_and_reads_token() {
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var(ENV_DATA_ROOT, dir.path());
        assert_eq!(resolve_data_root(), dir.path());

        assert_eq!(read_token(dir.path()), None);
        std::fs::create_dir_all(dir.path().join("config")).unwrap();
        std::fs::write(dir.path().join("config").join("api-token"), "secret\n").unwrap();
        assert_eq!(read_token(dir.path()), Some("secret".to_string()));

        std::env::remove_var(ENV_DATA_ROOT);
        assert!(resolve_data_root().ends_with("traduko"));
    }
}
