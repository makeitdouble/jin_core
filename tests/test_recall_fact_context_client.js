const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const base = 'ui/static/js/runtime/';
let saved;
const storage = {
  readBrowserMemory: () => saved,
  writeBrowserMemory: (_, value) => { saved = JSON.parse(JSON.stringify(value)); },
};
const sandbox = {window: {JinRuntime: {storage}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(base+'runtime-lt-memory.js','utf8'),sandbox);
const api=sandbox.window.JINRuntimeLTMemory;
const sources=[{session_id:'s',runtime_snapshot_id:'L1_one'},{session_id:'s',turn_id:'t1'}];
api.writeStore({facts:[{id:'F1',key:'city',value:'Kyiv',sources,created_at:'2026-01-01',updated_at:'2026-09-06'}]});
assert.deepStrictEqual(JSON.parse(JSON.stringify(api.readStore().facts[0].sources)),sources);
// Execute the actual intake writer with its normal boundary dependencies.
let fields={};
const intake={
  storage:{getCurrentFactsMemorySessionId:()=> 's'},
  readFactsMemory:()=>fields,writeFactsMemory:value=>{fields=value;},
  normalizeRuntimeMemoryKey:x=>x,stripRuntimeMemoryMeta:x=>x,
  isFactsMemoryExcludedKey:()=>false,isJinResponseRuntimeMemoryKey:()=>false,
  isActiveMemoryRuntimeMemoryLine:()=>false,deletedFactsMemoryKeys:new Set(),
  getFactsMemoryIdentity:x=>x,
};
vm.createContext(intake);
const runtime=fs.readFileSync(base+'runtime.js','utf8');
vm.runInContext(runtime.slice(runtime.indexOf('function persistRuntimeFactsMemory('),runtime.indexOf('function getFactsMemoryFields()')),intake);
intake.persistRuntimeFactsMemory({runtime_memory_id:'first',lines:[{key:'city',value:'Kyiv'}]});
intake.persistRuntimeFactsMemory({runtime_memory_id:'second',lines:[{key:'city',value:'Kyiv'}]});
assert.strictEqual(fields.city.runtime_snapshot_id,'first');
fields.city.lt_status='analyzed';
intake.persistRuntimeFactsMemory({runtime_memory_id:'third',lines:[{key:'city',value:'Kyiv'}]});
assert.strictEqual(fields.city.runtime_snapshot_id,'first');
intake.persistRuntimeFactsMemory({runtime_memory_id:'fourth',lines:[{key:'city',value:'Lviv'}]});
assert.strictEqual(fields.city.runtime_snapshot_id,'fourth');
assert.strictEqual(fields.city.lt_status,'pending');
// Existing tooltip projection retains dates and adds the source count.
const view=fs.readFileSync(base+'runtime-memory-view.js','utf8');
vm.runInContext(view.slice(view.indexOf('  function formatLongTermFactMetadata('),view.indexOf('  function buildLongTermMemoryLine(')),intake);
const lines=intake.formatLongTermFactMetadata({sources,created_at:'2026-01-01',updated_at:'2026-09-06'});
assert(lines.includes('sources: 2'));
assert(lines.includes('created_at: 2026-01-01'));
assert(lines.includes('updated_at: 2026-09-06'));
console.log('Recall fact context client: storage round trip, unchanged/changed intake, tooltip passed');
