//! Core process lifecycle: probe the port, spawn the bundled sidecar
//! (falling back to a PATH-installed `traduko`) when the core is not
//! running, and kill our own child on exit.
//! A core started by the user elsewhere is never touched.
//!
//! The sidecar is a PyInstaller one-folder build shipped as a bundle
//! resource. One-file was measured at seven seconds or more to answer
//! /health on every launch, because it re-extracts to a new temp path and
//! macOS re-validates every dylib; a stable path drops that to under a
//! second after the first run.

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

/// Locate the bundled sidecar inside a resource directory. The PyInstaller
/// one-folder build is copied there under `core/` (see bundle.resources in
/// tauri.conf.json), with the launcher next to its `_internal` payload.
pub fn find_core_binary(resource_dir: &Path) -> Option<PathBuf> {
    let candidate = resource_dir.join("core").join("traduko-core");
    candidate.exists().then_some(candidate)
}

fn core_command(app: &tauri::AppHandle) -> Command {
    use tauri::Manager;

    // The bundler copies the sidecar folder into the app's resource
    // directory (Contents/Resources in the .app bundle, the cargo target dir
    // under `tauri dev`). Fall back to a PATH-installed `traduko` for
    // developers who never built the sidecar and run the core from a venv.
    let sidecar = app
        .path()
        .resource_dir()
        .ok()
        .and_then(|dir| find_core_binary(&dir));
    let mut command = match sidecar {
        Some(path) => Command::new(path),
        None => Command::new("traduko"),
    };
    command.env("PATH", augmented_path());
    // Passed as an env var rather than a CLI flag so an older PATH-installed
    // `traduko` simply ignores it instead of failing on an unknown option.
    // A core that knows the variable exits itself when this app dies, which
    // covers force-quits and crashes where kill_managed never runs.
    command.env("TRADUKO_PARENT_PID", std::process::id().to_string());
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

/// True while a core we spawned is still alive. An exited child is cleared
/// from the slot so a later call can spawn a replacement.
fn managed_alive(managed: &mut Option<Child>) -> bool {
    match managed.as_mut().map(Child::try_wait) {
        Some(Ok(None)) => true,
        Some(_) => {
            *managed = None;
            false
        }
        None => false,
    }
}

/// Spawn the core unless one is already running. Called both from the setup
/// hook (before the webview boots) and from the frontend, so it must be
/// idempotent: a core we spawned moments ago is still booting and has no
/// open port yet, and spawning a second one would race for the port and
/// orphan the first child.
pub fn ensure_running(app: &tauri::AppHandle, state: &CoreProcess) -> &'static str {
    let mut managed = state.0.lock().unwrap();
    if managed_alive(&mut managed) {
        return "spawned";
    }
    if port_open(CORE_PORT) {
        return "already_running";
    }
    match core_command(app).arg("serve").spawn() {
        Ok(child) => {
            *managed = Some(child);
            "spawned"
        }
        Err(_) => "unavailable",
    }
}

#[tauri::command]
pub fn ensure_core_running(
    app: tauri::AppHandle,
    state: tauri::State<CoreProcess>,
) -> &'static str {
    ensure_running(&app, state.inner())
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
    use std::sync::{MutexGuard, PoisonError};

    // Command::spawn forks, and on macOS a socket built by another test
    // thread can leak into the child before CLOEXEC is set, leaving a
    // released port bound for as long as the child lives. Tests that bind a
    // port and tests that spawn a process take this lock so they never
    // overlap.
    static SPAWN_GUARD: Mutex<()> = Mutex::new(());

    fn exclusive() -> MutexGuard<'static, ()> {
        SPAWN_GUARD.lock().unwrap_or_else(PoisonError::into_inner)
    }

    #[test]
    fn port_open_detects_listener() {
        let _guard = exclusive();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(port_open(port));
        drop(listener);
        assert!(!port_open(port));
    }

    #[test]
    fn find_core_binary_looks_inside_the_bundled_core_folder() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(find_core_binary(dir.path()), None);
        // A launcher sitting loose in the resource dir is not the sidecar:
        // the one-folder build only works next to its `_internal` payload.
        std::fs::write(dir.path().join("traduko-core"), b"stub").unwrap();
        assert_eq!(find_core_binary(dir.path()), None);
        std::fs::create_dir(dir.path().join("core")).unwrap();
        let bin = dir.path().join("core").join("traduko-core");
        std::fs::write(&bin, b"stub").unwrap();
        assert_eq!(find_core_binary(dir.path()), Some(bin));
    }

    #[test]
    fn managed_alive_holds_a_running_child() {
        let _guard = exclusive();
        let child = Command::new("sleep").arg("30").spawn().unwrap();
        let mut managed = Some(child);
        assert!(managed_alive(&mut managed));
        // Still held, so ensure_running would not spawn a second core.
        assert!(managed.is_some());
        let _ = managed.take().unwrap().kill();
    }

    #[test]
    fn managed_alive_clears_an_exited_child() {
        let _guard = exclusive();
        let mut child = Command::new("true").spawn().unwrap();
        let _ = child.wait();
        let mut managed = Some(child);
        assert!(!managed_alive(&mut managed));
        // Slot cleared so a retry can spawn a replacement.
        assert!(managed.is_none());
    }

    #[test]
    fn managed_alive_is_false_without_a_child() {
        assert!(!managed_alive(&mut None));
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
