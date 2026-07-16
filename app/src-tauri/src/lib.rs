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
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(core_process::CoreProcess(std::sync::Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            connection_info,
            core_process::ensure_core_running
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                use tauri::Manager;
                core_process::kill_managed(&app_handle.state::<core_process::CoreProcess>());
            }
        });
}
