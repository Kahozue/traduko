import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { themeStore } from "./lib/theme";
import "@fontsource/noto-sans-tc/400.css";
import "@fontsource/noto-sans-tc/500.css";
import "@fontsource/noto-sans-tc/700.css";
import "./styles/tokens.css";
import "./styles/base.css";

themeStore.init();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
