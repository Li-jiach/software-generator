const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

const app = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
const tick = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};

function setup() {
  const elements = new Map();
  const requests = [], renders = [], saves = [], messages = [];
  const nodes = [
    { id: 'page', type: 'page', name: '业务页面', y: 0 },
    { id: 'shot1', type: 'screenshot', name: '截图 1', image: 'first-image', y: 100 },
    { id: 'shot2', type: 'screenshot', name: '截图 2', image: 'second-image', y: 200 }
  ];
  const links = [{ fromId: 'page', toId: 'shot1' }, { fromId: 'page', toId: 'shot2' }];
  const copy = value => JSON.parse(JSON.stringify(value));
  const ctx = vm.createContext({
    nodes, generated: {}, activeCopyrightId: 'test', profile: {},
    aiConfig: { endpoint: 'http://example.invalid', model: 'test', mode: 'chat', apiKey: '' },
    generationState: { running: false },
    $: selector => {
      if (!elements.has(selector)) elements.set(selector, { disabled: false, hidden: false, textContent: '', classList: { add() {}, remove() {} } });
      return elements.get(selector);
    }, $$: () => [],
    getNode: id => ctx.nodes.find(node => node.id === id),
    directTargets: id => links.filter(link => link.fromId === id).map(link => nodes.find(node => node.id === link.toId)),
    configuredAi: () => true,
    api: (url, options) => new Promise((resolve, reject) => requests.push({ url, body: JSON.parse(options.body), resolve, reject })),
    saveWorkspace: () => saves.push(copy(ctx.generated)),
    renderCanvas: () => { renders.push(copy(ctx.generated)); ctx.updateManualStatus(); },
    toast: (message, kind) => messages.push({ message, kind }),
    setTimeout, requestAnimationFrame: callback => setImmediate(callback)
  });
  vm.runInContext(app.slice(app.indexOf('function makeComponentQueue('), app.indexOf('function manualTreePayload(')), ctx);
  for (const name of ['screenshotOperation', 'normalizeGeneratedResult', 'generationNode']) vm.runInContext(app.match(new RegExp('^function ' + name + '\\(.*$', 'm'))[0], ctx);
  vm.runInContext(app.match(/^async function regenerateNode\(.*$/m)[0], ctx);
  vm.runInContext(app.slice(app.indexOf('function ensurePauseButton('), app.indexOf('async function downloadGeneratedManual(')), ctx);
  vm.runInContext(app.slice(app.indexOf('function updateGenerationStatus('), app.indexOf('setInterval(updateGenerationStatus')), ctx);
  vm.runInContext(app.slice(app.indexOf('function updateManualStatus('), app.indexOf("$('#regenerateBtn').addEventListener")), ctx);
  vm.runInContext(app.slice(app.indexOf('async function generateNext('), app.indexOf('async function restructureManual(')), ctx);
  return { ctx, requests, renders, saves, messages, elements, links };
}

const screenshotResult = id => ({ id, title: '记录查询', contentSummary: id + '查询功能', operation: id + '按钮功能详情' });

test('regenerating a connected screenshot only updates that screenshot', async () => {
  const { ctx, requests, links } = setup();
  links.splice(1, 1, { fromId: 'shot1', toId: 'shot2' });
  ctx.generated = { screenshots: { shot1: screenshotResult('shot1') } };
  const completion = ctx.regenerateNode(ctx.nodes[2], '补充功能说明');
  assert.equal(requests[0].body.node.id, 'shot2');
  assert.equal(requests[0].body.node.image, 'second-image');
  assert.ok(!requests[0].body.node.images);
  requests[0].resolve(screenshotResult('shot2'));
  await completion;
  assert.equal(ctx.generated.screenshots.shot1.operation, 'shot1按钮功能详情');
  assert.equal(ctx.generated.screenshots.shot2.operation, 'shot2按钮功能详情');
});

test('each completed component is displayed and saved before the next response', async () => {
  const { ctx, requests, renders, saves, elements } = setup();
  const completion = ctx.generateNext();
  assert.equal(requests.length, 1);
  requests[0].resolve(screenshotResult('shot1'));
  await tick();
  assert.equal(requests.length, 2);
  assert.equal(ctx.generated.screenshots.shot1.operation, 'shot1按钮功能详情');
  assert.ok(!ctx.generated.screenshots.shot2);
  assert.ok(renders.some(value => value.screenshots?.shot1 && !value.screenshots.shot2));
  assert.ok(saves.some(value => value.screenshots?.shot1 && !value.screenshots.shot2));
  assert.ok(elements.get('#generationText').textContent.includes('1/3'));
  assert.equal(elements.get('#restructureManualBtn').disabled, true);
  requests[1].resolve(screenshotResult('shot2'));
  await tick();
  assert.equal(requests.length, 3);
  assert.equal(requests[2].body.node.id, 'page');
  assert.equal(requests[0].body.node.image, 'first-image');
  assert.equal(requests[1].body.node.image, 'second-image');
  assert.equal(requests[2].url, '/manual/generate-component');
  assert.deepEqual(requests[2].body.children.map(child => child.generated), [{ contentSummary: 'shot1查询功能' }, { contentSummary: 'shot2查询功能' }]);
  assert.ok(!JSON.stringify(requests[2].body).includes('按钮功能详情'));
  requests[2].resolve({ contentSummary: '业务页面介绍' });
  await completion;
  assert.equal(ctx.generated.status, 'generated');
  assert.equal(elements.get('#restructureManualBtn').disabled, false);
  assert.equal(elements.get('#exportManualBtn').disabled, true);
  assert.ok(!('operation' in ctx.generated.nodes.page));
});

test('failed requests retain completed results and keep restructuring disabled', async () => {
  const { ctx, requests, saves, elements } = setup();
  const completion = ctx.generateNext();
  requests[0].resolve(screenshotResult('shot1'));
  await tick();
  requests[1].resolve({ error: true, detail: '模型调用失败' });
  await completion;
  assert.equal(ctx.generated.status, 'partial');
  assert.equal(ctx.generated.screenshots.shot1.operation, 'shot1按钮功能详情');
  assert.equal(saves.at(-1).status, 'partial');
  assert.equal(elements.get('#generateManualBtn').disabled, false);
  assert.equal(elements.get('#restructureManualBtn').disabled, true);
});

test('pause allows the current result to appear and waits before starting the next request', async () => {
  const { ctx, requests } = setup();
  const completion = ctx.generateNext();
  ctx.generationState.paused = true;
  requests[0].resolve(screenshotResult('shot1'));
  await tick();
  assert.equal(requests.length, 1);
  assert.ok(ctx.generated.screenshots.shot1);
  ctx.generationState.paused = false;
  await new Promise(resolve => setTimeout(resolve, 120));
  requests[1].resolve(screenshotResult('shot2'));
  await tick();
  requests[2].resolve({ contentSummary: '业务页面介绍' });
  await completion;
  assert.equal(ctx.generated.status, 'generated');
});

test('switching projects prevents a delayed response from overwriting the new workspace', async () => {
  const { ctx, requests } = setup();
  const completion = ctx.generateNext();
  ctx.activeCopyrightId = 'another-project';
  ctx.generationState = { running: false };
  ctx.generated = { nodes: { other: { contentSummary: '新项目介绍' } } };
  requests[0].resolve(screenshotResult('shot1'));
  await completion;
  assert.equal(ctx.generated.nodes.other.contentSummary, '新项目介绍');
  assert.ok(!ctx.generated.screenshots);
  assert.equal(requests.length, 1);
});
