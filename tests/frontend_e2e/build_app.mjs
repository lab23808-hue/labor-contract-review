import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(__dirname, "..");

await build({
  entryPoints: [path.join(__dirname, "harness_app.jsx")],
  bundle: true,
  outfile: path.join(__dirname, "harness_app.bundle.js"),
  format: "iife",
  jsx: "automatic",
  absWorkingDir: frontendDir,
  define: {
    "import.meta.env": JSON.stringify({ VITE_API_BASE_URL: "http://localhost:8000" }),
  },
  logLevel: "info",
});

const html = `<!doctype html>
<html><head><meta charset="utf-8"></head>
<body><script src="harness_app.bundle.js"></script></body></html>`;
fs.writeFileSync(path.join(__dirname, "harness_app.html"), html);
console.log("bundle 构建完成");
