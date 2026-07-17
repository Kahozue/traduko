# Traduko

[English](README.md) | 繁體中文

Traduko 是一個自動字幕翻譯的桌面應用程式。它對影片、音訊或字幕檔執行可設定的管線：抽取音軌、語音辨識、斷句、LLM 翻譯、可選的 agent 校對，最後輸出字幕。名稱取自世界語的「翻譯」。

專案是既有工具之上的編排層，不是新引擎：媒體處理用 ffmpeg，語音辨識用 faster-whisper，翻譯接任何 OpenAI 相容端點。

![任務儀表板](docs/screenshot-tasks-light.png)

![設定頁，深色主題](docs/screenshot-settings-dark.png)

## 功能

- 輸入可以是影片、音訊檔或既有字幕檔（SRT/VTT/ASS/TXT）。輸出格式為 SRT、VTT、ASS，可選擇硬燒進影片。
- 管線以 YAML profile 定義階段序列。階段可以增刪與調整參數，任意階段之後可以設置人工檢查點。
- 桌面應用內含字幕表格編輯器（逐句修改譯文）與 ASS 樣式編輯器（CSS 近似預覽加 ffmpeg 精確渲染幀）。存回修改會重置下游階段，任務可從該處續跑。
- 校對是帶工具的 agent 迴圈：可查詢名詞表與前後文，分多輪修訂譯文。強度可設定；若校對中途預算用盡，保留目前的最佳版本。
- Token 用量會計價與計量。任務達到預算上限時暫停，提高上限後可續跑。翻譯進度逐批寫入磁碟，中斷不會失去已完成的部分。
- 名詞表維持全檔術語一致。翻譯與校對的提示詞模板是資料目錄下的純文字檔，可直接編輯。
- 任務執行前會做預檢：輸入檔、ffmpeg、ASR 模型、LLM 憑證與預算。
- 任務事件可送往 Webhook、Discord 與 Email。Discord bot 提供 slash 指令（列出、執行、暫停、取消任務），並在頻道內維護一則隨進度更新的訊息。
- 設定、提示詞、名詞表與任務紀錄可以透過共享資料夾（例如 Dropbox 目錄）或 WebDAV 在多台機器間同步。名詞表逐列合併，衝突的列留給人工決定；其他機器的任務以唯讀顯示。
- 所有任務、產物與設定都是資料目錄下人類可讀的檔案。SQLite 只作為索引，隨時可以從檔案重建。

介面語言目前為繁體中文。

## 架構

```
+--------------------+        HTTP / WebSocket        +---------------------+
|  桌面應用          | <----------------------------> |  核心服務           |
|  (Tauri 2 + React) |        127.0.0.1 + token       |  (Python / FastAPI) |
+--------------------+                                +---------------------+
                                                          |
                                              管線階段：ffmpeg、
                                              faster-whisper、LLM 供應商
```

- `core/`：Python 引擎。任務模型、管線執行器、各階段實作、LLM/ASR 供應商抽象、常駐服務與 CLI。
- `app/`：Tauri 2 + React 19 桌面殼。只透過核心 API 運作；GUI 與 CLI 是對等的客戶端。

資料目錄預設在平台的使用者資料位置（macOS 為 `~/Library/Application Support/traduko`），可用環境變數 `TRADUKO_DATA_ROOT` 覆蓋。

## 安裝

目前從原始碼建置。需求：

- Python 3.11 以上與 [uv](https://docs.astral.sh/uv/)
- ffmpeg（媒體處理與硬燒）
- Node.js 與 pnpm、Rust 工具鏈（僅桌面應用需要）

### 引擎與 CLI

```bash
cd core
uv sync
uv run traduko --help
```

需要本地語音辨識時安裝 ASR extra：

```bash
uv sync --extra asr
```

### 桌面應用

開發模式（需要已啟動的 core，或 PATH 上有 `traduko`）：

```bash
cd app
pnpm install
pnpm tauri dev
```

發佈建置（將 core 以 PyInstaller 打包為 sidecar）：

```bash
bash core/packaging/build_sidecar.sh
cd app && pnpm tauri build
```

打包版的 core 不含 faster-whisper；需要本地 ASR 時請以 Python 環境執行 core。

## 使用

首次啟動會在資料目錄產生預設 profile（`av-default`、`subtitle-translate`）、提示詞模板、字幕樣式與計價表。這些都是帶註解的純文字檔，可以直接修改。

CLI 基本操作：

```bash
# 建立並執行一個字幕翻譯任務
uv run traduko task create input.srt --profile subtitle-translate
uv run traduko task run <task-id>

# 查看任務
uv run traduko task list
uv run traduko task show <task-id>

# 啟動常駐服務（桌面應用的後端）
uv run traduko serve
```

接上真實 LLM：在 `config/core.yaml` 的 `llm_providers` 下新增供應商（`base_url` 指向任何 OpenAI 相容端點，`api_key_env` 指定金鑰的環境變數），再把 profile 中 `translate` 與 `proofread` 階段的 `provider` 指向它。預設的 `fake` provider 供離線試跑使用。

## 開發

```bash
cd core && uv run pytest            # 引擎測試
cd app && pnpm test                 # 前端單元測試
cd app && pnpm test:integration     # 前後端整合測試
cd app/src-tauri && cargo test      # Rust 殼測試
```

## 路線圖

- 文件翻譯管線（長篇文本：Markdown/TXT/EPUB/HTML）
- TTS 配音
- 內建設定與診斷助理
- Anthropic 與 Gemini 原生 adapter
- 漫畫翻譯管線
