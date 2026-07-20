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

// Read a deliverable as text for the inline preview. Goes through the asset
// protocol rather than the core's artifact endpoint, which only speaks JSON.
// Throws outside Tauri (tests) and for anything the scope refuses.
export async function readArtifactText(path: string): Promise<string> {
  const { convertFileSrc } = await import("@tauri-apps/api/core");
  const response = await fetch(convertFileSrc(path));
  if (!response.ok) throw new Error(`asset read failed: ${response.status}`);
  return response.text();
}
