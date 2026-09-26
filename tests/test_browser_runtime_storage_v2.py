"""The legacy v2 API is now page-local; disk owns reload continuation."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserRuntimeStorageV2Tests(unittest.TestCase):
    def test_page_cache_cannot_migrate_or_restore_durable_browser_state(self):
        script = r'''
const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('ui/static/js/runtime/runtime-storage.js', 'utf8');
class Storage {
  constructor(seed={}) { this.data = new Map(Object.entries(seed)); }
  get length() { return this.data.size; }
  key(index) { return [...this.data.keys()][index] || null; }
  getItem(key) { return this.data.get(key) || null; }
  setItem(key, value) { this.data.set(key, String(value)); }
  removeItem(key) { this.data.delete(key); }
}
const checkpoint = {version:2, state:'checkpoint', session_id:'foreign',
 runtime_memory:'FOREIGN', session_snapshot:{tool_results:[{result:'FOREIGN'}]}};
const local = new Storage({
 'jin.sessionCheckpoint.v2':JSON.stringify(checkpoint),
 'jin.latestSavedSessionSnapshot.v1':JSON.stringify(checkpoint),
 'jin.latestRuntimeMemory.foreign.v1':JSON.stringify(checkpoint),
 'jin.activeMemory.v1':JSON.stringify(['FOREIGN']),
 'jin.factsMemory.foreign.v2':JSON.stringify({topic:{content:'FOREIGN'}}),
 'jin_bubble_skin':'bamboo',
});
let nextId=0;
function boot(blocked=false) {
 const window={sessionStorage:new Storage({'jin.liveRuntimeMemory.v2':JSON.stringify(checkpoint)}),
   crypto:{randomUUID:()=>`page-${++nextId}`}, JinRuntime:{}};
 Object.defineProperty(window,'localStorage',{get(){if(blocked) throw Error('denied'); return local;}});
 vm.runInNewContext(source,{window, console});
 return window.JinRuntime.storage;
}
const page = boot();
assert.equal(page.readSessionCheckpoint(),null);
assert.equal(page.readLatestRuntimeMemory(),null);
assert.equal(page.collectFactsMemoryRecords().length,0);
assert.equal(local.getItem('jin.sessionCheckpoint.v2'),null);
assert.equal(local.getItem('jin_bubble_skin'),'bamboo');
page.markSessionCheckpointUserActivity();
assert.equal(page.writeSessionCheckpoint(checkpoint),true);
assert.equal(page.readSessionCheckpoint().runtime_memory,'FOREIGN'); // explicit in-page projection
assert.equal(local.getItem('jin.sessionCheckpoint.v2'),null,'never durable');
const fresh = boot();
assert.equal(fresh.readSessionCheckpoint(),null,'reload/new tab cannot hydrate page RAM');
assert.equal(page.readSessionCheckpoint().runtime_memory,'FOREIGN','other page cannot overwrite live cache');
page.writeBrowserMemory('jin.factsMemory.source.v2',{topic:{content:'disk fact'}});
assert.equal(page.collectFactsMemoryRecords().length,1);
page.clearMemoryProjection();
assert.equal(page.collectFactsMemoryRecords().length,0);
assert.equal(boot(true).readSessionCheckpoint(),null,'restricted storage is optional');
console.log('PASS: disk-only bootstrap cache contract');
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
