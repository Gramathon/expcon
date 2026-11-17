import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync, mkdirSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {configuration, executable, workspace} from "../extensions/expcon.ts";
const root = mkdtempSync(join(tmpdir(), "expcon-extension-"));
test("workspace uses explicit research directory and rejects missing paths", () => {
  assert.equal(workspace("/", {EXPCON_WORKSPACE:root}), root);
  assert.throws(() => workspace(root, {EXPCON_WORKSPACE:join(root,"missing")}));
});
test("stdio discovers explicit executable without a source checkout", () => {
  const bin=join(root,"controller"); writeFileSync(bin,"#!/bin/sh\nexit 0\n",{mode:0o755});
  const c=configuration(root,{EXPCON_MCP_EXECUTABLE:bin});
  assert.deepEqual(c,{command:bin,args:["--stdio","--workspace",root],cwd:root,exposure:"direct"});
});
test("workspace environments and PATH discovery", () => {
  mkdirSync(join(root,".venv-mcp/bin"),{recursive:true});
  const bin=join(root,".venv-mcp/bin/expcon-mcp");writeFileSync(bin,"",{mode:0o755});
  assert.equal(executable("expcon-mcp",root,{}),bin);
  assert.equal(executable("expcon-mcp","/",{PATH:join(root,".venv-mcp/bin")}),bin);
  assert.throws(()=>executable("missing","/",{PATH:""}), /not found/);
});
test("HTTP explicitly accepts only loopback",()=>{
  assert.equal(configuration(root,{EXPCON_MCP_URL:"http://127.0.0.1:7680/mcp"}).url,"http://127.0.0.1:7680/mcp");
  for(const url of ["http://example.org/mcp","https://127.0.0.1/mcp","http://user:secret@localhost/mcp"])
    assert.throws(()=>configuration(root,{EXPCON_MCP_URL:url}),/loopback/);
});
