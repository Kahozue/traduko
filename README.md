# Traduko

開源全自動翻譯工作站。以管線編排整合語音辨識、LLM 翻譯與 AI 校對，一個檔案進、成品字幕出，全程可插入人工檢查點。

Traduko 是世界語的「翻譯」。專案定位是編排層：不重造引擎，而是把現有的開源引擎（ffmpeg、faster-whisper、任何 OpenAI 相容的 LLM 端點）串成可靠、可續跑、可審校的自動化流程。

## 功能

- **影音字幕管線**：影片或音檔進，抽取音軌、語音辨識、斷句、LLM 翻譯、AI agent 校對、輸出 SRT/VTT/ASS，可選硬燒字幕進影片。字幕檔（SRT/VTT/ASS/TXT）也可直接作為輸入。
- **管線是資料**：處理流程由 YAML profile 定義階段序列，可自由增刪階段、調整參數，任意階段後可設人工檢查點暫停待審。
- **人工審校**：桌面 App 內建字幕表格編輯器（逐句改譯文，校對標記一目了然）與 ASS 樣式編輯器（CSS 即時預覽加 ffmpeg 精確渲染幀）。存回修改會自動重置下游階段，續跑即生效。
- **AI agent 校對**：校對是帶工具的 agent 迴圈（查名詞表、讀上下文、逐句修訂），強度可調，預算耗盡時輸出目前最佳版本收斂。
- **成本控制**：內建 token 計價與預算計量，觸頂自動暫停任務，補預算後可續跑；翻譯進度以 partial artifact 落盤，中斷不丟已翻內容。
- **名詞表與提示詞**：名詞表強制術語一致；翻譯與校對的提示詞模板皆為資料根下的純文字檔，可直接編輯。
- **任務預檢**：執行前檢查輸入檔、ffmpeg、ASR 模型、LLM 金鑰與預算，問題先擋在開跑之前。
- **通知**：任務事件可推送 Webhook、Discord（webhook）與 Email。
- **桌面 App**：任務儀表板、WebSocket 即時事件流、亮暗雙主題、系統匣常駐（關窗不退出）；App 內建 core 執行檔，開箱即用。
- **資料開放**：所有任務、產物、設定都是資料根下人類可讀的分層檔案，檔案是唯一真相來源，SQLite 僅作查詢索引，可隨時重建。

介面語言目前為繁體中文。

## 架構

```
+--------------------+        HTTP / WebSocket        +---------------------+
|  Desktop App       | <----------------------------> |  Core service       |
|  (Tauri 2 + React) |        127.0.0.1 + token       |  (Python / FastAPI) |
+--------------------+                                +---------------------+
                                                          |
                                              pipeline stages: ffmpeg,
                                              faster-whisper, LLM providers
```

- `core/`：Python 引擎核心。任務模型、管線執行器、各階段實作、LLM/ASR 供應商抽象、常駐服務與 CLI。
- `app/`：Tauri 2 + React 19 桌面殼。所有功能走 core 的 API，GUI 與 CLI 是對等的客戶端。

資料根預設在使用者資料目錄（macOS 為 `~/Library/Application Support/traduko`），可用環境變數 `TRADUKO_DATA_ROOT` 覆蓋。

## 安裝

目前從原始碼建置。需求：

- Python 3.11 以上與 [uv](https://docs.astral.sh/uv/)
- ffmpeg（影音處理與硬燒）
- Node.js 與 pnpm、Rust 工具鏈（僅建置桌面 App 需要）

### 引擎核心與 CLI

```bash
cd core
uv sync
uv run traduko --help
```

需要本地語音辨識時安裝 ASR extra：

```bash
uv sync --extra asr
```

### 桌面 App

開發模式（需先啟動 core 或已安裝 `traduko` 於 PATH）：

```bash
cd app
pnpm install
pnpm tauri dev
```

打包成品（會將 core 以 PyInstaller 打包為 sidecar 一併封入）：

```bash
bash core/packaging/build_sidecar.sh
cd app && pnpm tauri build
```

打包版不含 faster-whisper；需要本地 ASR 請以 Python 環境執行 core。

## 使用

首次啟動會在資料根播種預設 profile（`av-default`、`subtitle-translate`）、提示詞模板、樣式與計價表，全部是帶註解的純文字檔，可直接修改。

CLI 快速上手：

```bash
# 建立並執行一個字幕翻譯任務
uv run traduko task create input.srt --profile subtitle-translate
uv run traduko task run <task-id>

# 查看任務
uv run traduko task list
uv run traduko task show <task-id>

# 啟動常駐服務（桌面 App 的後端）
uv run traduko serve
```

接上真實 LLM：在 `config/core.yaml` 的 `llm_providers` 下新增供應商（`base_url` 指向任何 OpenAI 相容端點，`api_key_env` 指定金鑰環境變數），再把 profile 中 `translate` 與 `proofread` 階段的 `provider` 指過去。預設的 `fake` provider 為離線試跑用。

## 開發

```bash
cd core && uv run pytest            # 引擎核心測試
cd app && pnpm test                 # 前端單元測試
cd app && pnpm test:integration     # 前後端整合測試（自動拉起臨時 core）
cd app/src-tauri && cargo test      # Rust 殼測試
```

## 路線圖

- 文件翻譯管線（長篇小說取向：Markdown/TXT/EPUB/HTML）
- TTS 配音
- Discord bot 雙向遙控
- 設定與提示詞的雲端同步（WebDAV）
- 漫畫翻譯管線
