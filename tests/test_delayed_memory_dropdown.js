// Run: node tests/test_delayed_memory_dropdown.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/static/js/runtime/runtime-memory-view.js'), 'utf8');
class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.style = {}; this.listeners = {};
    this.style.setProperty = (name, value) => { this.style[name] = value; };
    this.dataset = {}; this.className = ''; this.value = ''; this.selectionStart = 0; this.scrollLeft = 0;
    this.rect = {left: 300, bottom: 220, width: 80};
    this.classList = {
      add: name => { this.className += ' ' + name; },
      remove: name => { this.className = this.className.split(' ').filter(x => x !== name).join(' '); },
    };
  }
  append(...nodes) { nodes.forEach(n => this.appendChild(n)); }
  appendChild(node) { node.remove(); node.parent = this; this.children.push(node); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); this.parent = null; }
  contains(node) { return node === this || this.children.some(n => n.contains(node)); }
  setAttribute() {}
  set innerHTML(value) { this.children.forEach(n => n.parent = null); this.children = []; }
  addEventListener(name, fn) { (this.listeners[name] ||= new Set()).add(fn); }
  removeEventListener(name, fn) { this.listeners[name]?.delete(fn); }
  fire(name, props = {}) { [...(this.listeners[name] || [])].forEach(fn => fn({target: this, preventDefault() {}, stopPropagation() {}, ...props})); }
  focus() {} blur() {}
  get isConnected() { return this === body || Boolean(this.parent?.isConnected); }
  closest(selector) {
    if (this.className.split(' ').includes(selector.slice(1))) return this;
    return this.parent?.closest(selector) || null;
  }
  getBoundingClientRect() {
    if (this.className.includes('fact-dropdown')) return {width: 300, height: 132};
    if (this.tag === 'span') return {width: (this.textContent || '').length * 8};
    return this.rect;
  }
}
const body = new Element('body');
const document = new Element('document');
document.body = body; document.documentElement = {clientWidth: 1000, clientHeight: 600}; document.createElement = tag => new Element(tag);
const window = new Element('window');
window.innerWidth = 1000; window.innerHeight = 600;
window.getComputedStyle = () => ({font: '12px monospace', fontFamily: 'monospace', letterSpacing: '0px', paddingLeft: '0px'});
const frames = new Map();
let nextFrame = 0;
window.requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
window.cancelAnimationFrame = id => frames.delete(id);
function flushFrames() {
  const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback());
}
let hitElement = null;
document.elementFromPoint = () => hitElement;
let linkedFact, linkedFile;
const env = {document, window,
  persistentFileHoverCard: null, persistentFileHoverCardAnchor: null, persistentFileHoverRequestSerial: 0,
  persistentFileHoverRows: new WeakMap(),
  memoryPanel: {getBoundingClientRect: () => ({left: 800, right: 1000, width: 200})},
  activeDelayedMemoryFactPicker: null, activeDelayedMemoryAttachmentPicker: null,
  bindRuntimeMemoryHoverTitle() {}, bindPersistentFileHoverPreview() {}, dispatchDelayedMemoryAttachmentAvatarHover() {},
  getDelayedMemoryFactOptions: () => [{factId: 'F379', title: 'Fact', label: 'F379 . Fact'}],
  getDelayedMemoryAttachmentOptions: () => [{fileId: 'file1', record: {name: 'image.png'}}],
  normalizeDelayedMemoryFactIds: () => [], normalizeDelayedMemoryFactId: value => value,
  normalizeDelayedMemoryAttachmentIds: value => [value],
  linkFactToDelayedMemoryModal: id => {linkedFact = id;},
  linkAttachmentToDelayedMemoryModal: id => {linkedFile = id;},
};
vm.createContext(env);
for (const name of ['positionLongTermMemoryHoverCard', 'hidePersistentFileHoverCard', 'createDelayedMemoryPickerOverlay', 'closeActiveDelayedMemoryFactPicker', 'closeActiveDelayedMemoryAttachmentPicker', 'appendDelayedMemoryFactPicker', 'appendDelayedMemoryAttachmentPicker']) {
  const start = source.indexOf('  function ' + name + '(');
  const end = source.indexOf('\n  function ', start + 1);
  vm.runInContext(source.slice(start, end), env);
}
// Use the real outside-click handler, including its portal membership checks.
const modalStart = source.indexOf('  function ensureDelayedMemoryModal(');
const clickStart = source.indexOf('    document.addEventListener("click",', modalStart);
const clickEnd = source.indexOf('    document.addEventListener("keydown",', clickStart);
vm.runInContext(source.slice(clickStart, clickEnd), env);
for (const kind of ['Fact', 'Attachment']) {
  const container = new Element('div'); body.append(container);
  env['appendDelayedMemory' + kind + 'Picker'](container, ...(kind === 'Fact' ? [{}, []] : [[]]));
  container.fire('click');
  const state = env['activeDelayedMemory' + kind + 'Picker'];
  const input = container.children[0].children[0];
  const dropdown = state.dropdown;
  assert.equal(dropdown.parent, body, 'must escape the scroll/overflow ancestors');
  assert.equal(dropdown.style.left, '308px');
  assert.equal(dropdown.style.top, '227px');
  input.value = 'abcde'; input.selectionStart = 2; input.scrollLeft = 4;
  input.fire('input');
  assert.equal(dropdown.style.left, '320px', 'must track caret, not the end of the input');
  input.selectionStart = 4; input.fire('keyup');
  assert.equal(dropdown.style.left, '336px');
  input.rect.bottom = 300; document.fire('scroll', {target: container});
  assert.equal(dropdown.style.top, '307px');
  document.fire('click', {target: dropdown});
  assert.equal(dropdown.parent, body, 'clicking the portal must not close it');
  input.rect.left = 960; input.rect.bottom = 590; window.fire('resize');
  assert.equal(dropdown.style.left, '692px');
  assert.equal(dropdown.style.top, '460px');
  dropdown.children[0].fire('click');
  assert.equal(dropdown.parent, null);
  assert.equal(env['activeDelayedMemory' + kind + 'Picker'], null);
  assert.equal(window.listeners.resize.size, 0);
  assert.equal(document.listeners.scroll.size, 0);
  assert.equal(input.listeners.select.size, 0);
  container.fire('click');
  document.fire('click', {target: body});
  assert.equal(dropdown.parent, null);
  container.fire('click');
  input.fire('keydown', {key: 'Escape'});
  assert.equal(dropdown.parent, null);
}
assert.equal(linkedFact, 'F379'); assert.equal(linkedFile, 'file1');
const facts = new Element('div'), files = new Element('div'); body.append(facts, files);
env.appendDelayedMemoryFactPicker(facts, {}, []);
env.appendDelayedMemoryAttachmentPicker(files, []);
facts.fire('click'); const firstMenu = env.activeDelayedMemoryFactPicker.dropdown;
files.fire('click');
assert.equal(firstMenu.parent, null, 'opening files must close the facts portal');
env.closeActiveDelayedMemoryAttachmentPicker();
assert.equal(body.children.filter(n => n.className.includes('fact-dropdown')).length, 0);
// File preview must be placed beside the dropdown, not beside the memory panel.
files.fire('click');
const menu = env.activeDelayedMemoryAttachmentPicker.dropdown;
menu.getBoundingClientRect = () => ({left: 60, right: 360, top: 220, bottom: 352, width: 300, height: 132});
const anchor = menu.children[0];
anchor.rect = {left: 60, right: 360, top: 240, bottom: 264, width: 300, height: 24};
function attachPreview() {
  const card = new Element('div');
  card.getBoundingClientRect = () => ({width: 280, height: 280});
  body.append(card);
  env.persistentFileHoverCard = card; env.persistentFileHoverCardAnchor = anchor;
  env.positionLongTermMemoryHoverCard(card, anchor);
  return card;
}
let preview = attachPreview();
assert.equal(preview.style.left, '374px');
assert.equal(preview.dataset.placement, 'right');
assert.equal(preview.style['--runtime-memory-lt-hover-arrow-y'], '140px');
menu.getBoundingClientRect = () => ({left: 650, right: 950, top: 220, bottom: 352, width: 300, height: 132});
env.positionLongTermMemoryHoverCard(preview, anchor);
assert.equal(preview.style.left, '356px');
assert.equal(preview.dataset.placement, 'left', 'use the free side at the viewport edge');
// Ordinary memory-panel hovers retain their existing placement.
const normalAnchor = new Element('div'); body.append(normalAnchor);
normalAnchor.rect = anchor.rect;
env.positionLongTermMemoryHoverCard(preview, normalAnchor);
assert.equal(preview.style.left, '506px');
assert.equal(preview.dataset.placement, 'left');
// A stationary pointer must keep the same preview, or switch to the newly exposed file.
env.persistentFileHoverRows.set(anchor, {name: 'first.png'});
hitElement = anchor.children[0]; // Hit-testing can return the inner label.
menu.fire('pointermove', {clientX: 700, clientY: 250});
document.fire('scroll', {target: menu});
document.fire('scroll', {target: menu});
assert.equal(frames.size, 1, 'coalesce scroll events into one frame');
flushFrames();
assert.equal(env.persistentFileHoverCard, preview, 'same file keeps its preview');
assert.equal(preview.isConnected, true);
assert.equal(preview.style.left, '356px');
const nextOption = new Element('button');
nextOption.className = 'delayed-memory-modal-attachment-option';
nextOption.rect = anchor.rect;
menu.append(nextOption);
const nextRecord = {name: 'second.png'};
env.persistentFileHoverRows.set(nextOption, nextRecord);
let shownRecord = null;
env.showPersistentFileHoverCard = (option, record) => {
  env.hidePersistentFileHoverCard();
  shownRecord = record;
  const card = new Element('div'); body.append(card);
  env.persistentFileHoverCard = card; env.persistentFileHoverCardAnchor = option;
};
hitElement = nextOption;
document.fire('scroll', {target: menu});
flushFrames();
assert.equal(preview.parent, null, 'old file must be replaced after scrolling');
assert.equal(env.persistentFileHoverCardAnchor, nextOption);
assert.equal(shownRecord, nextRecord);
hitElement = menu;
document.fire('scroll', {target: menu}); flushFrames();
assert.equal(env.persistentFileHoverCard, null, 'blank space must not retain a preview');
hitElement = nextOption;
document.fire('scroll', {target: menu}); flushFrames();
assert.equal(env.persistentFileHoverCardAnchor, nextOption, 'preview returns without pointer movement');
menu.fire('pointerleave');
document.fire('scroll', {target: menu}); flushFrames();
assert.equal(env.persistentFileHoverCard, null, 'leaving the list prevents scroll from reopening a preview');
preview = attachPreview();
files.children[0].children[0].fire('input');
assert.equal(preview.parent, null, 'filtering must discard the detached option preview');
// Re-open to use the new option after filtering.
env.closeActiveDelayedMemoryAttachmentPicker();
files.fire('click');
const currentMenu = env.activeDelayedMemoryAttachmentPicker.dropdown;
const closingPreview = new Element('div'); body.append(closingPreview);
env.persistentFileHoverCard = closingPreview;
env.persistentFileHoverCardAnchor = currentMenu.children[0];
document.fire('scroll', {target: currentMenu});
assert.equal(frames.size, 1);
env.closeActiveDelayedMemoryAttachmentPicker();
assert.equal(frames.size, 0, 'closing cancels pending preview synchronization');
assert.equal(currentMenu.listeners.pointermove.size, 0);
assert.equal(currentMenu.listeners.pointerleave.size, 0);
assert.equal(closingPreview.parent, null);
assert.equal(env.persistentFileHoverCardAnchor, null);

const css = fs.readFileSync(path.join(__dirname, '../ui/static/css/runtime-memory.css'), 'utf8');
assert.match(css, /\.delayed-memory-modal-fact-dropdown\s*\{\s*position: fixed;/);
assert.ok(!css.includes('.delayed-memory-modal-fact-ids .delayed-memory-modal-fact-dropdown'));
console.log('PASS: fact/file portals, caret positioning, viewport bounds, scrolling, selection, outside click, Escape, cleanup');
