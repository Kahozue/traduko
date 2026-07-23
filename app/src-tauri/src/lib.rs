mod core_process;
mod paths;

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionInfo {
    pub base_url: String,
    pub token: Option<String>,
    pub data_root: String,
}

#[tauri::command]
fn connection_info() -> ConnectionInfo {
    let root = paths::resolve_data_root();
    ConnectionInfo {
        base_url: format!("http://127.0.0.1:{}", paths::CORE_PORT),
        token: paths::read_token(&root),
        data_root: root.display().to_string(),
    }
}

// Only files under the Traduko data root may be opened; the webview never
// gets a general "open any path" primitive. Reveal-in-Finder additionally
// accepts the asset-protocol scope (see checked_reveal_path), because task
// input files live wherever the user picked them.
fn checked_data_path(path: &str) -> Result<std::path::PathBuf, String> {
    let root = paths::resolve_data_root();
    let target = std::path::PathBuf::from(path);
    if !target.starts_with(&root) {
        return Err("path is outside the data root".into());
    }
    if !target.exists() {
        return Err("file not found".into());
    }
    Ok(target)
}

#[tauri::command]
fn open_artifact(path: String) -> Result<(), String> {
    let target = checked_data_path(&path)?;
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").arg(&target).status();
    #[cfg(target_os = "windows")]
    let status = std::process::Command::new("cmd")
        .args(["/C", "start", ""])
        .arg(&target)
        .status();
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let status = std::process::Command::new("xdg-open").arg(&target).status();
    status.map_err(|e| e.to_string()).and_then(|s| {
        if s.success() { Ok(()) } else { Err("opener exited with an error".into()) }
    })
}

// Mirrors tauri.conf.json's assetProtocol scope ($HOME, /Volumes, /tmp):
// paths the webview may already read, it may also reveal (never execute).
fn checked_reveal_path(path: &str) -> Result<std::path::PathBuf, String> {
    let target = std::path::PathBuf::from(path);
    if !target.exists() {
        return Err("file not found".into());
    }
    if target.starts_with(paths::resolve_data_root())
        || target.starts_with("/Volumes")
        || target.starts_with("/tmp")
        || std::env::var("HOME").is_ok_and(|home| target.starts_with(&home))
        || std::env::var("USERPROFILE").is_ok_and(|home| target.starts_with(&home))
    {
        Ok(target)
    } else {
        Err("path is outside the allowed scope".into())
    }
}

#[tauri::command]
fn reveal_artifact(path: String) -> Result<(), String> {
    let target = checked_reveal_path(&path)?;
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").arg("-R").arg(&target).status();
    #[cfg(target_os = "windows")]
    let status = std::process::Command::new("explorer")
        .arg(format!("/select,{}", target.display()))
        .status();
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let status = std::process::Command::new("xdg-open")
        .arg(target.parent().unwrap_or(&target))
        .status();
    status.map_err(|e| e.to_string()).and_then(|s| {
        if s.success() { Ok(()) } else { Err("opener exited with an error".into()) }
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri::Manager;

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(core_process::CoreProcess(std::sync::Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            connection_info,
            open_artifact,
            reveal_artifact,
            core_process::ensure_core_running
        ])
        .setup(|app| {
            use tauri::menu::{Menu, MenuItem};
            use tauri::tray::TrayIconBuilder;

            // Start the core here rather than waiting for the webview to
            // boot and call ensure_core_running: the two then overlap
            // instead of running back to back. Off the main thread because
            // the port probe blocks for up to 300 ms. The frontend still
            // makes its own call, which ensure_running answers without
            // spawning a second core.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let state = handle.state::<core_process::CoreProcess>();
                core_process::ensure_running(&handle, state.inner());
            });

            // Tray menu copy is zh-TW by product decision; the TS i18n
            // dictionary is webview-only and cannot reach native menus.
            let show = MenuItem::with_id(app, "show", "顯示主視窗", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "結束", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window keeps the app resident in the tray; the
            // core child (if we spawned one) keeps running for CLI and bots.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| match event {
            tauri::RunEvent::Exit => {
                core_process::kill_managed(&app_handle.state::<core_process::CoreProcess>());
            }
            #[cfg(target_os = "macos")]
            tauri::RunEvent::Reopen { .. } => {
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            _ => {}
        });
}
