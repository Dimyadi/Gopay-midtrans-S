import express from "express";
import { spawn } from "child_process";
import { createProxyMiddleware } from "http-proxy-middleware";
import http from "http";

const app = express();
const PORT = 3000;
const DJANGO_PORT = 8000;
const DJANGO_HOST = "127.0.0.1";

let djangoProcess: any = null;
let djangoReady = false;

function startDjango() {
  console.log("Starting Django server on port " + DJANGO_PORT + "...");
  djangoProcess = spawn("python3", ["manage.py", "runserver", `${DJANGO_HOST}:${DJANGO_PORT}`, "--noreload"], {
    stdio: "inherit",
    env: { ...process.env, PYTHONUNBUFFERED: "1" }
  });

  djangoProcess.on("error", (err: any) => {
    console.error("Failed to start Django process:", err);
  });

  djangoProcess.on("exit", (code: number, signal: string) => {
    console.log(`Django process exited with code ${code} (${signal}). Restarting in 2s...`);
    djangoReady = false;
    setTimeout(startDjango, 2000);
  });
}

function checkDjangoHealth() {
  const req = http.get(`http://${DJANGO_HOST}:${DJANGO_PORT}/`, (res) => {
    if (res.statusCode && res.statusCode < 500) {
      djangoReady = true;
    }
  });
  req.on("error", () => {
    djangoReady = false;
  });
  req.setTimeout(1000, () => {
    req.destroy();
  });
}

// Check Django every second
setInterval(checkDjangoHealth, 1000);
startDjango();

// API Health
app.get("/api/health", (req, res) => {
  res.json({
    status: "ok",
    djangoReady,
    service: "midtrans-subscription-demo"
  });
});

// Proxy middleware to Django
const djangoProxy = createProxyMiddleware({
  target: `http://${DJANGO_HOST}:${DJANGO_PORT}`,
  changeOrigin: true,
  ws: true,
  logLevel: "warn",
  onError: (err, req, res: any) => {
    console.log("Django proxy connection error, waiting for Django...", err.message);
    if (!res.headersSent) {
      res.writeHead(503, { "Content-Type": "text/html; charset=utf-8" });
      res.end(`
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>Memuat Server Django...</title>
          <meta http-equiv="refresh" content="2">
          <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center min-h-screen font-sans p-4">
          <div class="bg-white p-8 rounded-2xl shadow border border-slate-200 text-center max-w-md">
            <div class="animate-spin w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full mx-auto mb-4"></div>
            <h2 class="text-xl font-bold text-slate-800 mb-2">Memulai Django Server...</h2>
            <p class="text-slate-500 text-sm">Sedang menghubungkan ke Midtrans Subscription Demo. Halaman akan otomatis memuat ulang dalam 2 detik.</p>
          </div>
        </body>
        </html>
      `);
    }
  }
});

app.use("/", djangoProxy);

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Express gateway running on http://0.0.0.0:${PORT} -> proxying to Django :${DJANGO_PORT}`);
});
