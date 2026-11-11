// Writes apps/web/openapi.json from the FastAPI app (mock mode, no database needed).
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..", "..");
const py = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const res = spawnSync(py, ["-m", "apps.api.export_openapi", resolve(here, "..", "openapi.json")], {
  cwd: root,
  stdio: "inherit",
});
process.exit(res.status ?? 1);
