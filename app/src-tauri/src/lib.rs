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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri::Manager;

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(core_process::CoreProcess(std::sync::Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            connection_info,
            core_process::ensure_core_running
        ])
        .setup(|app| {
            use tauri::menu::{Menu, MenuItem};
            use tauri::tray::TrayIconBuilder;

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
