/**
 * EXPCON MCP adapter — project-local Pi extension.
 *
 * Registers the EXP CON MCP server, exposes diagnostic commands,
 * and ensures the research skill is available.
 */

import { type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import * as child_process from "node:child_process";
import * as path from "node:path";
import * as fs from "node:fs";

export default function (pi: ExtensionAPI) {
  function getWorkspaceRoot() {
    if (process.env.EXPCON_WORKSPACE) return path.resolve(process.env.EXPCON_WORKSPACE);
    // Try to find the workspace root from cwd or config
    try {
      const expconDir = fs.realpathSync.native(path.join(process.cwd(), ".expcon"));
      return path.dirname(expconDir);
    } catch {
      return process.cwd();
    }
  }

  function localExecutable(name: string) {
    const workspaceRoot = getWorkspaceRoot();
    for (const environment of [".venv-mcp", ".venv"]) {
      const executable = path.join(workspaceRoot, environment, "bin", name);
      if (fs.existsSync(executable)) return executable;
    }
    return name === "python" ? "python3" : name;
  }

  // ──────────── MCP registration ────────────
  function registerExpconMcp() {
    const serverName = "expcon";
    const workspaceRoot = getWorkspaceRoot();

    const url = process.env.EXPCON_MCP_URL;
    pi.registerMcpServer(serverName, url
      ? { url, exposure: "direct" }
      : {
          command: localExecutable("expcon-mcp"),
          args: ["--stdio", "--workspace", workspaceRoot],
          cwd: workspaceRoot,
          exposure: "direct",
        });

  }

  // ──────────── Diagnostic tool ────────────
  pi.registerTool({
    name: "expcon_diagnose",
    label: "EXPCON Diagnose",
    description: "Check EXPCON MCP server connectivity and workspace status.",
    parameters: Type.Object({}),
    async execute() {
      const workspaceRoot = getWorkspaceRoot();
      const result: Record<string, any> = { workspace: workspaceRoot };

      // Check if .expcon directory exists
      const expconDir = path.join(workspaceRoot, ".expcon");
      result.has_control_dir = fs.existsSync(expconDir);

      // Check experiments directory
      const expsDir = path.join(workspaceRoot, "experiments");
      result.experiments_dir = fs.existsSync(expsDir)
        ? fs.readdirSync(expsDir).filter((f) => fs.statSync(path.join(expsDir, f)).isDirectory()).length
        : 0;

      // Try to list runs
      const runDir = path.join(expconDir, "runs");
      if (fs.existsSync(runDir)) {
        result.run_count = fs.readdirSync(runDir).length;
      }

      // Check Python availability
      try {
        const output = child_process.execFileSync(
          localExecutable("python"),
          ["-c", "import expcon_mcp; print(expcon_mcp.__version__)"],
          { env: { ...process.env, PYTHONPATH: path.join(workspaceRoot, "src") }, timeout: 5000 }
        );
        result.python_import = output.toString().trim();
      } catch (err) {
        result.python_import = "import failed";
      }

      // Check if CLI works
      try {
        const output = child_process.execFileSync(
          localExecutable("expcon"),
          ["doctor", "--json"],
          { env: { ...process.env, PYTHONPATH: path.join(workspaceRoot, "src") }, timeout: 5000, cwd: workspaceRoot }
        );
        result.cli_status = JSON.parse(output.toString()).status || "ok";
      } catch {
        result.cli_status = "unavailable";
      }

      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  });

  // ──────────── Command: /expcon-status ────────────
  pi.registerCommand("expcon-status", {
    description: "Display EXPCON workspace status and MCP connectivity.",
    handler: async (_args, ctx) => {
      try {
        const output = child_process.execFileSync(
          localExecutable("expcon"),
          ["doctor", "--json"],
          { env: { ...process.env, PYTHONPATH: path.join(getWorkspaceRoot(), "src") }, timeout: 5000, cwd: getWorkspaceRoot() }
        );
        ctx.ui.notify(`EXPCON status: ${JSON.parse(output.toString()).status}`, "info");
      } catch (err) {
        ctx.ui.notify("EXPCON CLI unavailable", "warning");
      }
    },
  });

  // ──────────── Startup hooks ────────────
  pi.on("session_start", async (_event, ctx) => {
    registerExpconMcp();
  });

  // ──────────── Resources discovery ────────────
  pi.on("resources_discover", async (event, _ctx) => {
    const workspaceRoot = event.cwd || getWorkspaceRoot();
    const skillsDir = path.join(workspaceRoot, ".pi", "skills");
    return { skillPaths: [skillsDir] };
  });

  // ──────────── Footer status ────────────
  pi.on("turn_end", async (event, ctx) => {
    if (event.outcome === "completed") {
      ctx.ui.setStatus("expcon", "Expcon configured; use /mcp to inspect connectivity");
    }
  });
}
