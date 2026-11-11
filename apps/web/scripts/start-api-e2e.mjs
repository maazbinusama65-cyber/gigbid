// Starts the FastAPI app in mock mode for Playwright with a fresh sqlite file and fast streaming.
import { spawn } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..", "..");
const dbDir = resolve(here, "..", ".e2e");
mkdirSync(dbDir, { recursive: true });
const dbFile = resolve(dbDir, "gigbid-e2e.db");
rmSync(dbFile, { force: true });

const py = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const child = spawn(py, ["-m", "uvicorn", "apps.api.main:app", "--port", "8000", "--log-level", "warning"], {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    GIGBID_SERVICES: "mock",
    DATABASE_URL: `sqlite:///${dbFile.split("\\").join("/")}`,
    APP_SECRET_KEY: "e2e-only-secret-key",
    REVIEWER_EMAIL: "reviewer@gigbid.test",
    REVIEWER_PASSWORD: "e2e-reviewer-pass",
    MOCK_STREAM_DELAY_MS: process.env.MOCK_STREAM_DELAY_MS ?? "120",
    PASSWORD_SCRYPT_N: "1024",
  },
});
child.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill());
