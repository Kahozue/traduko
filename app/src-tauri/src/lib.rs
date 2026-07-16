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
        .invoke_handler(tauri::generate_handler![connection_info])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
