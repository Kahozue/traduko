// Open or reveal files in the OS shell via the Rust commands, which only
// accept paths under the Traduko data root. No-ops outside Tauri (tests).

export async function openArtifact(path: string): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_artifact", { path });
}

export async function revealArtifact(path: string): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("reveal_artifact", { path });
}
