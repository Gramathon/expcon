/** Thin Pi adapter: all scientific operations remain in the installed controller. */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { existsSync, accessSync, constants } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, resolve, join, delimiter } from "node:path";

export function workspace(cwd: string, env = process.env): string {
  const root = resolve(env.EXPCON_WORKSPACE || cwd);
  if (!existsSync(root)) throw new Error(`EXPCON workspace does not exist: ${root}`);
  return root;
}

export function executable(name: string, root: string, env = process.env): string {
  const explicit = name === "expcon-mcp" ? env.EXPCON_MCP_EXECUTABLE : env.EXPCON_EXECUTABLE;
  const candidates = explicit ? [explicit] : [
    ...(name === "expcon" && env.EXPCON_MCP_EXECUTABLE ? [join(dirname(env.EXPCON_MCP_EXECUTABLE), name)] : []),
    ...[".venv-mcp", ".venv"].map(v => join(root, v, "bin", name)),
    ...(env.PATH || "").split(delimiter).map(p => join(p, name)),
  ];
  for (const candidate of candidates) {
    try { accessSync(candidate, constants.X_OK); return resolve(candidate); } catch { /* continue */ }
  }
  throw new Error(`${name} not found. Install the Expcon wheel with [mcp], or set ${name === "expcon-mcp" ? "EXPCON_MCP_EXECUTABLE" : "EXPCON_EXECUTABLE"}.`);
}

export function configuration(cwd: string, env = process.env) {
  const root = workspace(cwd, env);
  if (env.EXPCON_MCP_URL) {
    const url = new URL(env.EXPCON_MCP_URL);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password)
      throw new Error("EXPCON_MCP_URL must be a loopback HTTP URL without credentials.");
    return { url: url.href, exposure: "direct" as const };
  }
  return {command: executable("expcon-mcp", root, env), args: ["--stdio", "--workspace", root], cwd: root, exposure: "direct" as const};
}

export default function expcon(pi: ExtensionAPI) {
  // The compatibility shim and an installed package may both be discovered.
  if (pi.getMcpServers().some(server => server.name === "expcon")) return;
  let error: string | undefined;
  try {
    // Register during load. Pi gives an existing mcp.json entry precedence.
    pi.registerMcpServer("expcon", configuration(process.cwd()));
  } catch (e) { error = String(e); }

  function diagnose(cwd: string) {
    const root = workspace(cwd);
    const config = configuration(cwd);
    // No PYTHONPATH injection or assumptions about the workload interpreter.
    const env = {...process.env};
    delete env.PYTHONPATH;
    const cli = executable("expcon", root);
    const version = execFileSync(cli, ["--version"], {cwd: root, env, timeout: 10000, encoding: "utf8"}).trim();
    const doctor = JSON.parse(execFileSync(cli, ["doctor", "--json"], {cwd: root, env, timeout: 10000, encoding: "utf8"}));
    return {workspace: root, version, controller: config, doctor, connectivity: "Use /mcp to inspect the host-managed connection."};
  }
  pi.registerTool({
    name: "expcon_diagnose", label: "Expcon diagnostics",
    description: "Inspect the installed Expcon executable, workspace and local configuration. Use /mcp for connection status.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      try { return {content: [{type: "text", text: JSON.stringify(diagnose(ctx.cwd), null, 2)}], details: {error: false}}; }
      catch (e) { return {content: [{type: "text", text: String(e)}], details: {error: true}}; }
    },
  });
  pi.registerCommand("expcon-status", {
    description: "Check installed Expcon and workspace; /mcp shows connectivity.",
    async handler(_args, ctx) {
      try { ctx.ui.notify(JSON.stringify(diagnose(ctx.cwd)), "info"); }
      catch (e) { ctx.ui.notify(String(e), "error"); }
    },
  });
  pi.on("session_start", async (_event, ctx) => {
    if (error) ctx.ui.notify(error, "error");
    ctx.ui.setStatus("expcon", error ? "Expcon unavailable; /expcon-status" : "Expcon configured; /mcp");
  });
  // Skills are declared in the package manifest, not inferred from workspace/src.
}
