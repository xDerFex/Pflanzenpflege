const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const project = path.resolve(__dirname, '..');
const care = fs.readFileSync(path.join(project, 'static/care.js'), 'utf8').replaceAll('export ', '');
const app = fs.readFileSync(path.join(project, 'static/app.js'), 'utf8')
  .replace(/^import[^\n]*\n/, '').replace(/start\(\);\s*$/, '');
const roots = {
  app: { innerHTML: '' },
  'sheet-root': { innerHTML: '', dataset: {}, querySelector: () => ({ addEventListener() {} }) },
  'toast-root': { innerHTML: '' },
};
const listeners = {};
const sandbox = {
  document: {
    querySelector(selector) { return roots[selector.slice(1)] || null; },
    addEventListener(name, callback) { listeners[name] = callback; },
  },
  crypto: { getRandomValues: crypto.webcrypto.getRandomValues.bind(crypto.webcrypto) },
  window: {}, Date, Intl, Math, Number, String, Array, Map, Set, URL, JSON,
  structuredClone, setTimeout, clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(care + '\n' + app, sandbox);

async function click(action) {
  const target = {
    dataset: { action, id: '' },
    classList: { contains() { return false; } },
    closest() { return this; },
  };
  await listeners.click({ target });
  return roots['sheet-root'].innerHTML;
}

(async () => {
  assert.match(await click('room-form'), /id="room-form"/);
  assert.match(await click('plant-form'), /id="plant-form"/);
  assert.equal(roots['toast-root'].innerHTML, '');
  console.log('Room and plant forms open without crypto.randomUUID');
})().catch(error => { console.error(error); process.exitCode = 1; });
