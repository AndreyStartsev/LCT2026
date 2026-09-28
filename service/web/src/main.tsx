import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Шрифты макета собраны в клиент: интерфейс не зависит от доступа в интернет
import "@fontsource/pt-sans/400.css";
import "@fontsource/pt-sans/700.css";
import "@fontsource/pt-sans/400-italic.css";
import "@fontsource/pt-sans-narrow/400.css";
import "@fontsource/pt-sans-narrow/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource/caveat/500.css";
import "@fontsource/caveat/600.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
