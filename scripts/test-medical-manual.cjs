const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'frontend/test-assets/medical-manual');
const manifest = JSON.parse(fs.readFileSync(path.join(assets, 'manifest.json')));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
let serial = 0;
const context = vm.createContext({
  sampleProfile: {},
  nodeSize: node => node.type === 'screenshot' ? { width: 260, height: 245 } : { width: 220, height: 168 },
  uid: () => `test-${++serial}`,
  $: () => ({ addEventListener() {} })
});
vm.runInContext(fs.readFileSync(path.join(root, 'frontend/test-case.js'), 'utf8'), context);
const images = new Map(manifest.screenshots.map(shot => [shot.file,
  `data:image/jpeg;base64,${fs.readFileSync(path.join(assets, shot.file)).toString('base64')}`]));
const graph = context.createTestManualGraph(manifest, images);

test('source and every extracted screenshot match the saved inventory', () => {
  assert.equal(hash(path.join(root, manifest.source.path)), manifest.source.sha256);
  assert.equal(hash(path.join(assets, manifest.source.file)), manifest.source.sha256);
  assert.equal(manifest.screenshots.length, 37);
  for (const shot of manifest.screenshots) assert.equal(hash(path.join(assets, shot.file)), shot.sha256);
  assert.equal(fs.existsSync(path.join(assets, 'shot-007.jpg')), false);
});

test('all original headings and screenshots occur once with correct parents', () => {
  assert.equal(graph.nodes.length, 51);
  assert.equal(graph.connections.length, 50);
  assert.equal(new Set(graph.nodes.map(node => node.id)).size, 51);
  for (const [type, count] of Object.entries({ system: 1, module: 4, page: 9, screenshot: 37 })) {
    assert.equal(graph.nodes.filter(node => node.type === type).length, count);
  }
  for (const node of graph.nodes) {
    const links = graph.connections.filter(link => link.toId === node.id);
    assert.equal(links.length, node.type === 'system' ? 0 : 1);
    if (!links.length) continue;
    const parent = graph.nodes.find(item => item.id === links[0].fromId);
    const expected = node.type === 'screenshot' ? node.sourceNumber
      : manifest.headings.find(heading => heading.number === node.sourceNumber).parent;
    assert.equal(parent.sourceNumber, expected);
    assert.ok(node.x > parent.x);
  }
  for (const node of graph.nodes.filter(node => node.type === 'screenshot')) {
    assert.ok(node.image.startsWith('data:image/jpeg;base64,'));
  }
});

test('layout has no overlapping components', () => {
  for (let i = 0; i < graph.nodes.length; i++) {
    for (const b of graph.nodes.slice(i + 1)) {
      const a = graph.nodes[i];
      assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);
    }
  }
});

test('production generation queue visits every child before its parent', () => {
  const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
  context.nodes = graph.nodes;
  context.directTargets = id => graph.connections.filter(link => link.fromId === id)
    .map(link => graph.nodes.find(node => node.id === link.toId));
  vm.runInContext(app.slice(app.indexOf('function makeComponentQueue()'), app.indexOf('function componentChildren(')), context);
  const queue = context.makeComponentQueue();
  assert.equal(queue.length, 51);
  for (const link of graph.connections) {
    assert.ok(queue.findIndex(node => node.id === link.toId) < queue.findIndex(node => node.id === link.fromId));
  }
  assert.equal(queue.at(-1).type, 'system');
});

test('missing images fail instead of importing an incomplete fixture', () => {
  assert.throws(() => context.createTestManualGraph(manifest, new Map()), /截图素材不完整/);
});

test('generation visits each screenshot and legacy chain helpers retain image order', () => {
  const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
  const nodes = [
    { id: 'page', type: 'page', name: '业务页面' },
    { id: 'tail', type: 'screenshot', name: '截图 3', image: 'tail-image' },
    { id: 'head', type: 'screenshot', name: '截图 1', image: 'head-image' },
    { id: 'middle', type: 'screenshot', name: '截图 2', image: 'middle-image' },
    { id: 'alone', type: 'screenshot', name: '截图 4', image: 'alone-image' }
  ];
  const connections = [
    { fromId: 'page', toId: 'head' }, { fromId: 'head', toId: 'middle' },
    { fromId: 'middle', toId: 'tail' }, { fromId: 'page', toId: 'alone' }
  ];
  const ctx = vm.createContext({ nodes, connections,
    getNode: id => nodes.find(node => node.id === id),
    directTargets: id => connections.filter(link => link.fromId === id).map(link => nodes.find(node => node.id === link.toId))
  });
  vm.runInContext(app.slice(app.indexOf('function screenshotChainIndex('), app.indexOf('function renderNode(')), ctx);
  vm.runInContext(app.slice(app.indexOf('function makeComponentQueue('), app.indexOf('function componentChildren(')), ctx);
  assert.deepEqual(Array.from(ctx.makeComponentQueue(), node => node.id), ['tail', 'middle', 'head', 'alone', 'page']);
  assert.deepEqual(Array.from(ctx.screenshotChain(nodes[2]), node => node.image), ['head-image', 'middle-image', 'tail-image']);
  assert.equal(ctx.generationNode(nodes[2]).image, 'head-image');
  assert.equal(ctx.generationNode(nodes[1]).image, 'tail-image');
  assert.equal(ctx.screenshotChainIndex(nodes[1]), 3);
  assert.equal(ctx.screenshotChainIndex(nodes[4]), 1);
  assert.equal(ctx.generationNode(nodes[2]).name, '截图 1');
  assert.equal(nodes[2].name, '截图 1');
});
