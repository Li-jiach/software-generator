// Run against the local Java server. This creates one isolated test project.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8080/');
    await page.waitForLoadState('networkidle');
    await page.locator('[data-view="test"]').click();
    await page.locator('#testBuildManualBtn').click();
    await page.waitForFunction(() => document.querySelector('#testState').textContent === '已构建'
      && document.querySelector('#manualCopyrightSelect').value === String(JSON.parse(localStorage.getItem('studioActiveCopyrightV2'))), null, { timeout: 30000 });
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('.manual-node-image').count(), 37);
    assert.ok(await page.locator('.manual-node-image').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0)));
    const id = await page.locator('#manualCopyrightSelect').inputValue();
    assert.match(id, /^\d+$/);
    const saved = await (await page.request.get(`http://127.0.0.1:8080/api/copyrights/${id}/workspace`)).json();
    assert.equal(saved.nodes.length, 51);
    assert.equal(saved.connections.length, 50);
    assert.equal(saved.generated.status, 'draft');
    assert.equal(saved.generated.fixtureId, 'medical-manual-v1');
    assert.equal(saved.nodes.filter(node => node.image?.startsWith('data:image/jpeg;base64,')).length, 37);
    const archive = await page.request.get(`http://127.0.0.1:8080/api/copyrights/${id}/materials/download`);
    assert.equal(archive.status(), 200);
    assert.equal((await archive.body()).subarray(0, 2).toString(), 'PK');
    await page.screenshot({ path: path.resolve(__dirname, '../tmp/medical-manual/canvas-desktop.png') });
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.locator('[data-view="manual"]').click();
    assert.equal(await page.locator('.manual-node').count(), 51);
    assert.equal(await page.locator('#manualCopyrightSelect').inputValue(), id);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ projectId: id, nodes: 51, connections: 50, screenshots: 37, reload: 'passed', materials: 'passed' }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
