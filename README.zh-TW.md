<div align="center">

<img src="docs/icon.png" width="128" height="128" alt="Traduko" />

# Traduko

桌面端的自動字幕與文件翻譯工具 — 抽取音軌、語音辨識、LLM 翻譯、agent 校對、輸出，一條管線完成。

[文件](README.zh-TW.md) · [English](README.md) · [架構](#架構) · [安裝](#安裝)

</div>

---

Traduko 對影片、音訊或字幕檔執行可設定的管線：抽取音軌、語音辨識、斷句、LLM 翻譯、可選的 agent 校對，最後輸出字幕。名稱取自世界語的「翻譯」。

專案是既有工具之上的編排層，不是新引擎：媒體處理用 ffmpeg，語音辨識用 faster-whisper，翻譯接任何 OpenAI 相容端點。

![任務儀表板，依專案分組，側欄提供各任務域檢視](docs/screenshot-tasks-light.png)

![任務詳情：內建播放器、工作室入口、管線開關與各階段進度](docs/screenshot-task-light.png)

![產出依類型分組，音訊就地播放，字幕檔就地預覽並可調字級](docs/screenshot-outputs-light.png)

![字幕編輯器，譯文與校對標註都可直接輸入](docs/screenshot-editor-light.png)

![ASS 樣式編輯器，附即時 CSS 近似預覽](docs/screenshot-style-light.png)

![配音工作室：引擎與參數、說話人與參考音、逐段試聽](docs/screenshot-dub-light.png)

![內建助理將設定變更整理成可核准的 diff，深色主題](docs/screenshot-assistant-dark.png)

![設定頁：外觀、介面語言與 LLM 供應商，深色主題](docs/screenshot-settings-dark.png)

![語音辨識引擎選單與配音引擎，深色主題](docs/screenshot-asr-dark.png)

![預算帳本：各模型花費占比與排行，深色主題](docs/screenshot-budget-dark.png)

## 功能

- 輸入可以是影片、音訊檔或既有字幕檔（SRT/VTT/ASS/TXT）。輸出格式為 SRT、VTT、ASS，可選擇硬燒進影片。
- 管線以 YAML profile 定義階段序列。階段可以增刪與調整參數，任意階段之後可以設置人工檢查點。
- 桌面應用內含字幕表格編輯器（逐句修改譯文）與 ASS 樣式編輯器（CSS 近似預覽加 ffmpeg 精確渲染幀）。校對標註與文件的品質標註和譯文欄位一樣可直接輸入，與譯稿一同存回；標註本身不是管線輸入，改動不會重置下游階段。存回譯文則會重置下游階段，任務可從該處續跑。
- 任務頁內建影音播放器與三個全屏工作室：配音工作室（TTS 引擎與參數、配音文本選譯文或原文、說話人參考音、試聽與兩層重配）、匯出工作室（影片與音頻編碼參數、輸出估算與磁碟空間檢查、以追加階段執行匯出）、翻譯設定（目標語言與提示詞覆寫、重新翻譯）。
- 產出依影片、音訊、圖片、文件分類列出。音訊直接在列上播放，含進度拖曳與倍速；字幕與純文字產出可就地展開預覽並調整字級；其餘格式交給系統開啟。
- 影音任務的翻譯、說話人分離、配音三段可在任務頁獨立開關。關閉的階段標記為略過並保留既有產物，重新開啟後接續執行；從未含配音階段的任務開啟配音時，自動在尾端補上配音階段群。
- 說話人分離為選用。關閉時語音合成以單一聲音進行，配音流程不受阻斷；開啟配音也不會把已關閉的說話人分離連同它的人工檢查點一併帶回。
- 翻譯預設依任務域（影片、音頻、文件）設定目標語言、風格與提示詞覆寫，建任務時自動套用，單一任務可再覆寫。
- 「製作音頻」與「製作影片」從逐字稿直接產出配音成品：逐字稿可以是磁碟上的 srt/vtt/txt 或既有任務的產物，合成語音後音頻直接輸出、影片則混入指定的影片檔。純文字逐字稿沒有時間碼時，語音片段依序首尾相接。
- 校對是帶工具的 agent 迴圈：可查詢名詞表與前後文，分多輪修訂譯文。強度可設定；若校對中途預算用盡，保留目前的最佳版本。
- Token 用量會計價與計量。任務達到預算上限時暫停，提高上限後可續跑。翻譯進度逐批寫入磁碟，中斷不會失去已完成的部分。
- 名詞表以多表管理維持術語一致：各表綁定單一任務域或通用，支援分類、CSV/JSON 匯入匯出。任務可複選全域表並疊加任務專屬表；名詞表同時偏置語音辨識（支援的引擎注入提示，其餘可插入輕量校對階段），修改後可對既有任務重新套用。翻譯與校對的提示詞模板是資料目錄下的純文字檔，可直接編輯。
- 內建助理可查詢任務狀態、預算、設定、日誌與預檢結果，並讀取任務產物的內容：逐字稿、譯文、校對與品質標註、說話人指派，以及字幕與純文字成品。它不能自行修改設定，只能提出待審提案，由操作者在面板核准後才生效。
- 任務執行前會做預檢：輸入檔、ffmpeg、ASR 模型、LLM 憑證與預算。
- 任務事件可送往 Webhook、Discord 與 Email。Discord bot 提供 slash 指令（列出、執行、暫停、取消任務），並在頻道內維護一則隨進度更新的訊息。
- 設定、提示詞、名詞表與任務紀錄可以透過共享資料夾（例如 Dropbox 目錄）或 WebDAV 在多台機器間同步。名詞表逐列合併，衝突的列留給人工決定；其他機器的任務以唯讀顯示。
- 所有任務、產物與設定都是資料目錄下人類可讀的檔案。SQLite 只作為索引，隨時可以從檔案重建。

介面語言可切換繁體中文、English、日本語。

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

macOS（Apple silicon）可從 [Releases](https://github.com/Kahozue/traduko/releases) 下載 dmg，內含打包好的核心，不需另外安裝 Python。應用未經 Apple 公證，首次開啟需在「系統設定 → 隱私權與安全性」放行。

其餘平台，或需要本地語音辨識時，從原始碼建置。需求：

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

首次啟動會在資料目錄產生預設 profile（`av-default`、`av-dub`、`subtitle-translate`、`novel-translate`、`translate-pdf`、`audio-transcribe`、`audio-translate`、`audio-dub`、`video-compose`、`audio-compose`）、提示詞模板、字幕樣式與計價表。這些都是帶註解的純文字檔，可以直接修改。

CLI 基本操作：

```bash
# 建立並執行一個字幕翻譯任務
uv run traduko task create input.srt --profile subtitle-translate
uv run traduko task run <task-id>

# 查看任務
uv run traduko task list
uv run traduko task show <task-id>

# 從逐字稿製作配音音頻
uv run traduko task create --profile audio-compose --transcript lines.srt

# 管線開關、翻譯設定、配音參數與追加匯出（無旗標為讀取）
uv run traduko task switches <task-id> --no-dub
uv run traduko task translate-opts <task-id> --target-language ja
uv run traduko task dub-params <task-id> --voice-mode design
uv run traduko task export <task-id> --kind audio --source dub

# 啟動常駐服務（桌面應用的後端）
uv run traduko serve
```

接上真實 LLM：在桌面應用「設定 → 一般」新增供應商（OpenAI 相容端點、Anthropic 或 Gemini），多個供應商時再選一個預設。profile 中 `provider` 為 `fake` 或未指定的階段會自動採用這個預設，不需要改 YAML。也可以直接編輯 `config/core.yaml` 的 `llm_providers` 與 `default_provider`，效果相同。未設定任何供應商時，`fake` provider 供離線試跑使用，輸出為帶 `[T]` 前綴的占位文字。

## 開發

```bash
cd core && uv run pytest            # 引擎測試
cd app && pnpm test                 # 前端單元測試
cd app && pnpm test:integration     # 前後端整合測試
cd app/src-tauri && cargo test      # Rust 殼測試
```

## 路線圖

- 漫畫翻譯管線
