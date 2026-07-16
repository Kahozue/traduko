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
    match sidecar {
        Some(path) => Command::new(path),
        None => Command::new("traduko"),
    }
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
}
