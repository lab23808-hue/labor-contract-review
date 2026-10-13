import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 最小 Vite 配置：只挂 React 插件，开发端口用默认的 5173
// （与后端 CORS 里放行的 http://localhost:5173 保持一致）。
export default defineConfig({
  plugins: [react()],
});
