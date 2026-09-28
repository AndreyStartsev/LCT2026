import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// В разработке запросы к API проксируются на сервис из docker compose.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/api": { target: env.API_URL || "http://localhost:3000", changeOrigin: true } },
    },
  };
});
