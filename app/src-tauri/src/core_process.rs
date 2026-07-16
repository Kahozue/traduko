//! Core process lifecycle: probe the port, spawn the bundled sidecar
//! (falling back to a PATH-installed `traduko`) when the core is not
//! running, and kill our own child on exit.
//! A core started by the user elsewhere is never touched.

use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use crate::paths::CORE_PORT;

pub struct CoreProcess(pub Mutex<Option<Child>>);

pub fn port_open(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

pub fn find_core_binary(dir: &Path) -> Option<PathBuf> {
    let candidate = dir.join("traduko-core");
    candidate.exists().then_some(candidate)
}

fn core_command() -> Command {
    // The Tauri bundler drops externalBin next to the app executable (both
    // in dev target dirs and inside the .app bundle). Fall back to a
    // PATH-installed `traduko` for developers running the core from a venv.
    let sidecar = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|d| d.to_path_buf()))
        .and_then(|dir| find_core_binary(&dir));
    let mut command = match sidecar {
        Some(path) => Command::new(path),
        None => Command::new("traduko"),
    };
    command.env("PATH", augmented_path());
    command
}

/// A GUI app launched from Finder/Dock inherits a minimal PATH that omits
/// Homebrew and other common install locations, so the core cannot find
/// ffmpeg/ffprobe. Prepend the usual tool directories to whatever PATH we
/// were given.
fn augmented_path() -> String {
    let extra = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
        "/usr/bin",
        "/bin",
    ];
    let current = std::env::var("PATH").unwrap_or_default();
    let mut parts: Vec<&str> = extra.to_vec();
    for entry in current.split(':').filter(|segment| !segment.is_empty()) {
        if !parts.contains(&entry) {
            parts.push(entry);
        }
    }
    parts.join(":")
}

#[tauri::command]
pub fn ensure_core_running(state: tauri::State<CoreProcess>) -> &'static str {
    if port_open(CORE_PORT) {
        return "already_running";
    }
    match core_command().arg("serve").spawn() {
        Ok(child) => {
            *state.0.lock().unwrap() = Some(child);
            "spawned"
        }
        Err(_) => "unavailable",
    }
}

pub fn kill_managed(state: &CoreProcess) {
    if let Some(mut child) = state.0.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn port_open_detects_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(port_open(port));
        drop(listener);
        assert!(!port_open(port));
    }

    #[test]
    fn find_core_binary_prefers_sibling_sidecar() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(find_core_binary(dir.path()), None);
        let bin = dir.path().join("traduko-core");
        std::fs::write(&bin, b"stub").unwrap();
        assert_eq!(find_core_binary(dir.path()), Some(bin));
    }

    #[test]
    fn augmented_path_prepends_homebrew_without_duplicates() {
        let path = augmented_path();
        let dirs: Vec<&str> = path.split(':').collect();
        assert!(dirs.contains(&"/opt/homebrew/bin"));
        assert!(dirs.contains(&"/usr/local/bin"));
        // No directory appears twice even if the inherited PATH overlaps.
        let mut seen = std::collections::HashSet::new();
        for dir in dirs {
            assert!(seen.insert(dir), "duplicate path entry: {dir}");
        }
    }
}
