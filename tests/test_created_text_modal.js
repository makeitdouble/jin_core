const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const base = path.join(__dirname, '../ui/static/js');
const attachments = fs.readFileSync(path.join(base, 'chat-attachments.js'), 'utf8');
const logger = fs.readFileSync(path.join(base, 'logger/log-entries.js'), 'utf8');
const extract = (source, first, last) => source.slice(source.indexOf(`function ${first}(`), source.indexOf(`function ${last}(`));

const ctx = {
  URL,
  ASSET_TEXT_PREVIEW_ENDPOINT: '/api/assets/text-preview',
  ASSET_TEXT_PREVIEW_MAX_CHARS: 60000,
  window: {jinRuntimeSessionId: 'live-session', location: {origin: 'http://jin.local'}},
  fetched: [],
  opened: [],
  normalizeAttachmentValue: x => String(x ?? ''),
  formatAttachmentHoverTitle: a => a.name || 'attachment',
  fetch: async function(url) {
    this.fetched.push(String(url));
    return {ok:true, json:async()=>({name:'caption_test/44.txt', type:'text/plain', kind:'text', text_content:'saved caption'})};
  },
  openJinAttachmentModal: async function(a) { this.opened.push(await a.resolve_modal_attachment()); },
};
// Explicit closures avoid relying on VM's implicit this.
ctx.fetch = async url => {
  ctx.fetched.push(String(url));
  return {ok:true, json: async()=>({name:'caption_test/44.txt', type:'text/plain', kind:'text', text_content:'saved caption'})};
};
ctx.openJinAttachmentModal = async a => { ctx.opened.push(await a.resolve_modal_attachment()); };
vm.createContext(ctx);
vm.runInContext(extract(attachments, 'getAssetResultPath', 'normalizeDelayedMemoryReportForModal'), ctx);
vm.runInContext(extract(logger, 'formatInternalAttachmentFailureText', 'log_internal_action'), ctx);

const duplicated = 'ATTACH_FILE_CONTENT: caption_test/44.txt - failed: Path not found inside linked folder: 44.txt.';
assert.equal(ctx.formatInternalAttachmentFailureText(duplicated, 'Path not found inside linked folder: 44.txt.', 'ATTACH_FILE_CONTENT'), duplicated);
assert.equal(ctx.formatInternalAttachmentFailureText('ATTACH_FILE_CONTENT: x', 'file missing', 'ATTACH_FILE_CONTENT'), 'ATTACH_FILE_CONTENT: x\nFAILED: file missing');

const listeners = {};
const classes = new Set();
const element = {
  classList: {add:(...items)=>items.forEach(x=>classes.add(x)), remove:(...items)=>items.forEach(x=>classes.delete(x))},
  addEventListener:(name,fn)=>(listeners[name] ||= []).push(fn),
  setAttribute(){}, removeAttribute(){},
};
ctx.bindAssetResultPreview(element,{ok:true,action:'create_asset_file',path:'caption_test/44.txt'});
ctx.bindAssetResultPreview(element,{ok:true,action:'create_asset_file',path:'caption_test/45.txt'});
assert.equal(listeners.click.length,1,'same action bubble must not accumulate click handlers');
assert.ok(classes.has('cursor-pointer'));
listeners.click[0]({preventDefault(){}});
setImmediate(()=>{
  assert.equal(ctx.opened.length,1);
  assert.equal(ctx.opened[0].text_content,'saved caption');
  const url = new URL(ctx.fetched[0]);
  assert.equal(url.searchParams.get('path'),'caption_test/45.txt','latest file must be previewed');
  assert.equal(url.searchParams.get('session_id'),'live-session');
  ctx.bindAssetResultPreview(element,null);
  listeners.click[0]({preventDefault(){}});
  assert.equal(ctx.opened.length,1,'retired result must not open old modal');
  console.log('PASS created text modal, click rebinding, link restriction and failure de-dup');
});
