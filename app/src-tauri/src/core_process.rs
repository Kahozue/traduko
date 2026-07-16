//! Core process lifecycle: probe the port, spawn `traduko serve` from
//! PATH when the core is not running, and kill our own child on exit.
//! A core started by the user elsewhere is never touched.

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use crate::paths::CORE_PORT;

pub struct CoreProcess(pub Mutex<Option<Child>>);

pub fn port_open(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

#[tauri::command]
pub fn ensure_core_running(state: tauri::State<CoreProcess>) -> &'static str {
    if port_open(CORE_PORT) {
        return "already_running";
    }
    match Command::new("traduko").arg("serve").spawn() {
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
}
