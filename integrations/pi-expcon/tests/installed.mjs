/** Real Pi package manager + SDK + installed MCP. No model calls or provider keys. */
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createAgentSession, createMcpExtension, DefaultResourceLoader, SessionManager, SettingsManager} from '@earendil-works/pi-coding-agent';
const [source, workspaceArg, reportArg] = process.argv.slice(2);
const packageDir=source.startsWith('git:') ? source : resolve(source);
const workspace=resolve(workspaceArg), reportPath=resolve(reportArg);
const agentDir = mkdtempSync(join(tmpdir(),'expcon-clean-pi-'));
process.env.PI_CODING_AGENT_DIR=agentDir;
process.env.EXPCON_WORKSPACE=workspace;
process.chdir(workspace);
const cli= new URL('../node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js',import.meta.url);
// Script lives in tests/, host dependencies live one level up.
cli.pathname=cli.pathname.replace('/tests/node_modules/','/node_modules/');
execFileSync(process.execPath,[cli.pathname,'install',packageDir],{env:process.env,cwd:workspace,stdio:'pipe'});
const settings=SettingsManager.create(workspace,agentDir);
if(process.env.EXPCON_TEST_CONFIGURED_MCP){
  writeFileSync(join(agentDir,'mcp.json'),JSON.stringify({mcpServers:{expcon:{command:process.env.EXPCON_MCP_EXECUTABLE,args:['--stdio','--workspace',workspace],cwd:workspace,exposure:'direct'}}}));
  // This unreachable extension URL must lose to the configured stdio server.
  process.env.EXPCON_MCP_URL='http://127.0.0.1:1/mcp';
}
const solConfig={version:1,actionFusion:false,observationPack:true,evidencePreservingReducer:false,onlineContextCompact:true,cacheWriteReadRatio:12.5};
if(process.env.SOL_PI_PACKAGE) writeFileSync(join(agentDir,'sol-pi.json'),JSON.stringify(solConfig));
const extra=process.env.SOL_PI_PACKAGE ? [process.env.SOL_PI_PACKAGE] : [];
const errors=[];
async function start(){
  const loader=new DefaultResourceLoader({cwd:workspace,agentDir,settingsManager:settings,additionalExtensionPaths:extra,extensionFactories:[createMcpExtension()]});
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors,[]);
  assert(loader.getSkills().skills.some(s=>s.name==='expcon-research'),'packaged research skill missing');
  const {session}=await createAgentSession({cwd:workspace,agentDir,resourceLoader:loader,settingsManager:settings,sessionManager:SessionManager.inMemory()});
  session.extensionRunner.onError(e=>errors.push(e));
  await session.bindExtensions({});
  for(let i=0;i<200;i++){
    if(session.getAllTools().some(t=>t.name==='mcp__expcon__expcon_doctor')) {
      assert.equal(session.getAllTools().filter(t=>t.name==='mcp__expcon__expcon_doctor').length,1);
      return session;
    }
    await new Promise(r=>setTimeout(r,50));
  }
  throw new Error('MCP tools not connected: '+JSON.stringify(errors));
}
let session;
let id=0;
async function call(name,args={}){
  const parent='release-'+id++;
  // Scripted assistant fixture: no model endpoint or credentials are used.
  session.agent.state.messages.push({role:'assistant',content:[{type:'toolCall',id:parent,name:'release_fixture',arguments:{}}],api:'test',provider:'test',model:'scripted',stopReason:'toolUse',timestamp:Date.now(),usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
  const ctx=session.extensionRunner.createToolContext(parent,undefined);
  const outcome=await ctx.executeTool(name==='expcon_diagnose' ? name : 'mcp__expcon__'+name,args);
  assert(!outcome.isError,JSON.stringify(outcome));
  const raw=outcome.result.structuredContent;
  if(raw?.structuredContent) return raw.structuredContent;
  const texts=(raw?.content || outcome.result.content).filter(x=>x.type==='text').map(x=>x.text);
  return JSON.parse(texts.join('\n'));
}
const report={host:'Pi 1.5.2',solPi:process.env.SOL_PI_PACKAGE||null,solConfig:process.env.SOL_PI_PACKAGE ? solConfig : null,results:[],status:'STARTED'};
try{
  session=await start();
  assert(session.getAllTools().some(t=>t.name==='expcon_diagnose'));
  const doctor=await call('expcon_doctor');assert.equal(doctor.workspace,workspace);
  const diagnostics=await call('expcon_diagnose');assert(diagnostics.version.includes(doctor.version));
  assert.equal(diagnostics.workspace,workspace);
  const command=session.extensionRunner.getCommand('expcon-status');assert(command);
  await command.handler('',session.extensionRunner.createCommandContext());
  const cases=JSON.parse(readFileSync(join(workspace,'cases.json'),'utf8'));
  for(const c of cases){
    await call('experiment_init',{experiment:c.experiment,contract:c.contract});
    await call('experiment_inspect',{experiment:c.experiment});
    await call('experiment_validate',{experiment:c.experiment});
    const candidate=await call('experiment_preflight',{experiment:c.experiment});
    await call('experiment_freeze',{experiment:c.experiment,expected_candidate_id:candidate.candidate_id});
    assert.equal((await call('experiment_diff',{experiment:c.experiment})).divergence_detected,false);
    const bundle=await call('experiment_bundle',{experiment:c.experiment});
    assert.equal((await call('bundle_verify',{bundle:bundle.bundle_path,expected_bundle_id:bundle.bundle_id})).status,'PASS');
    const args={experiment:c.experiment,idempotency_key:c.expected,inputs:{dataset:'data/dataset.json'}};
    const run=await call('experiment_run',args);
    // Simulate a lost client after dispatch, then reconnect and retry the same request.
    await session.extensionRunner.emit({type:'session_shutdown',reason:'exit'});
    session.dispose();
    session=await start();
    assert.equal((await call('experiment_run',args)).run_id,run.run_id,'duplicate execution after reconnect');
    let complete=false;
    for(let i=0;i<400;i++){
      const state=await call('experiment_status',{run_id:run.run_id});
      assert(!['ERROR','BLOCKED'].includes(state.status),JSON.stringify(state));
      assert(!['FAILED_EXECUTION','BLOCKED'].includes(state.state),JSON.stringify(state));
      if(state.state==='RESULTS_AVAILABLE'){complete=true;break;}
      await new Promise(r=>setTimeout(r,50));
    }
    assert(complete,'CPU completion timeout');
    const fetched=await call('experiment_fetch',{run_id:run.run_id});
    assert.equal((await call('experiment_verify',{run_id:run.run_id})).verified,true);
    const result=await call('experiment_adjudicate',{run_id:run.run_id});
    assert.equal(result.scientific_verdict,c.expected);
    assert.equal(result.execution_status,'COMPLETED');
    assert((await call('experiment_artifacts',{run_id:run.run_id})).items.length>0);
    await call('research_record_decision',{interpretation:'Release fixture: '+c.expected,referenced_runs:[run.run_id]});
    report.results.push({run_id:run.run_id,verdict:result.scientific_verdict,execution:result.execution_status});
    writeFileSync(join(fetched.evidence_path,'outputs/metrics.json'),'{"accuracy":0}');
    assert.equal((await call('experiment_verify',{run_id:run.run_id})).verified,false);
    assert.equal((await call('experiment_adjudicate',{run_id:run.run_id})).scientific_verdict,'INCONCLUSIVE');
  }
  const history=await call('research_history');assert.equal(history.runs.count,2);assert.equal(history.decisions.count,2);
  assert.deepEqual(errors,[]);
  report.status='PASS';report.recovery='same idempotency keys retained run IDs';report.corruption='INVALID / INCONCLUSIVE';
}finally{
  if(session){await session.extensionRunner.emit({type:'session_shutdown',reason:'exit'});session.dispose();}
  writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n');
}
console.log(JSON.stringify(report));
