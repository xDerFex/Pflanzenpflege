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
assert.equal(vm.runInContext('interval({...newPlant(),substrate:"Wasser"})', sandbox), 3);
const normalInterval = vm.runInContext('interval(newPlant())', sandbox);
const tallInterval = vm.runInContext('interval({...newPlant(),heightCM:80})', sandbox);
assert.equal(tallInterval, Math.max(2, normalInterval - 1));

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
  const plantForm = await click('plant-form');
  assert.match(plantForm, /id="plant-form"/);
  assert.match(plantForm, /data-wizard-step="4"/);
  assert.doesNotMatch(plantForm, /name="milestoneDate"/);
  assert.match(plantForm, /Abstand zum Fenster \(cm\)/);
  const preservedForm = { marker: 'form with unsaved values' };
  roots['sheet-root'].firstElementChild = preservedForm;
  roots['sheet-root'].replaceChildren = node => { roots['sheet-root'].restored = node; };
  vm.runInContext('openSheet("Info", "Information", "", true); closeSheet()', sandbox);
  assert.equal(roots['sheet-root'].restored, preservedForm);
  assert.equal(roots['toast-root'].innerHTML, '');
  console.log('Room and plant forms open without crypto.randomUUID');
})().catch(error => { console.error(error); process.exitCode = 1; });
