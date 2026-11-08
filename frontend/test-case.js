const testCaseProfile = { ...sampleProfile, shortName: '影像运维' };
const testManualAssetRoot = 'test-assets/medical-manual/';

function testNode(type, name, x, y, extra = {}) {
  const size = nodeSize({ type });
  return { id: uid('test'), type, name, x, y, width: size.width, height: size.height, selected: false, layoutVersion: 2, ...extra };
}

function testLink(from, to) {
  return { id: uid('test-link'), fromId: from.id, toId: to.id };
}

function createTestManualGraph(manifest, images) {
  const testNodes = [], testConnections = [], headings = new Map();
  for (const heading of manifest.headings) {
    const node = testNode(heading.type, heading.title, 0, 0, {
      sourceNumber: heading.number, sourcePage: heading.page, sourceLevel: heading.sourceLevel,
      fixtureId: manifest.id
    });
    headings.set(heading.number, node);
    testNodes.push(node);
  }
  for (const heading of manifest.headings) {
    if (heading.parent) {
      const parent = headings.get(heading.parent);
      if (!parent) throw new Error(`标题缺少父节点：${heading.number}`);
      testConnections.push(testLink(parent, headings.get(heading.number)));
    }
  }
  for (const shot of manifest.screenshots) {
    const parent = headings.get(shot.section), image = images.get(shot.file);
    if (!parent || !image?.startsWith('data:image/')) throw new Error(`截图素材不完整：${shot.file}`);
    const node = testNode('screenshot', shot.title, 0, 0, {
      image, fileName: shot.file, sourcePage: shot.page, sourceNumber: shot.section,
      sourceImageIndex: shot.index, sourceSha256: shot.sha256, fixtureId: manifest.id
    });
    testNodes.push(node);
    testConnections.push(testLink(parent, node));
  }
  // Each leaf has its own row; parents align with their first descendant.
  const columns = { system: 40, module: 350, page: 660, screenshot: 970 };
  let row = 50;
  const layout = node => {
    node.x = columns[node.type];
    node.y = row;
    const children = testConnections.filter(link => link.fromId === node.id)
      .map(link => testNodes.find(child => child.id === link.toId));
    if (children.length) children.forEach(layout);
    else row += nodeSize(node).height + 45;
  };
  manifest.headings.filter(heading => !heading.parent).forEach(heading => layout(headings.get(heading.number)));
  return { nodes: testNodes, connections: testConnections };
}

async function fetchTestAsset(file) {
  const response = await fetch(`${testManualAssetRoot}${file}`);
  if (!response.ok) throw new Error(`无法读取真实案例文件：${file}（${response.status}）`);
  return response;
}

async function buildTestManual() {
  if (generationState.running) {
    toast('当前手册仍在生成，请完成后再导入测试案例', 'error');
    return;
  }
  const button = $('#testBuildManualBtn'), original = button.textContent;
  button.disabled = true;
  $('#testFillFoundationBtn').disabled = true;
  button.textContent = '正在读取真实手册…';
  let project = null, committed = false;
  try {
    const manifest = await (await fetchTestAsset('manifest.json')).json();
    const images = new Map(), materials = new FormData();
    for (const shot of manifest.screenshots) {
      const image = await (await fetchTestAsset(shot.file)).blob();
      images.set(shot.file, await fileToDataUrl(image));
      materials.append('files', image, shot.file);
    }
    for (const file of ['source.pdf', 'outline.md', 'manifest.json']) {
      materials.append('files', await (await fetchTestAsset(file)).blob(), file);
    }
    const graph = createTestManualGraph(manifest, images);
    const nextGenerated = { status: 'draft', screenshots: {}, nodes: {}, fixtureId: manifest.id };
    const workspace = { profile: { ...testCaseProfile }, aiConfig, ...graph, generated: nextGenerated };
    // Flush the current project before switching; never write fixture nodes into it.
    clearTimeout(workspaceTimer);
    if (activeCopyrightId && /^[0-9]+$/.test(String(activeCopyrightId))) {
      await api(`/copyrights/${activeCopyrightId}/workspace`, {
        method: 'PUT', body: JSON.stringify({ profile, aiConfig, nodes, connections, generated })
      });
    }
    button.textContent = '正在保存测试项目…';
    project = await api('/copyrights', {
      method: 'POST', body: JSON.stringify({ ...testCaseProfile, name: `${manifest.title}（真实手册测试）`, status: '草稿', assetPath: '' })
    });
    if (!project?.id) throw new Error('测试项目创建失败');
    const upload = await fetch(`${backendOrigin}/api/copyrights/${project.id}/materials`, { method: 'POST', body: materials });
    if (!upload.ok) throw new Error(`源材料保存失败（${upload.status}）`);
    project.assetPath = (await upload.json()).assetPath;
    await api(`/copyrights/${project.id}/workspace`, { method: 'PUT', body: JSON.stringify(workspace) });
    committed = true;
    activeCopyrightId = project.id;
    copyrights.unshift(project);
    profile = workspace.profile;
    nodes = graph.nodes;
    connections = graph.connections;
    generated = nextGenerated;
    generationState = { running: false, paused: false, queue: [], index: 0, currentNodeId: '' };
    localPersist();
    renderProfile();
    switchView('manual');
    canvasZoom = Math.min(1, Math.max(.5, ($('#canvas').clientWidth - 30) / 1270));
    renderCanvas();
    renderLibrary();
    $('#canvas').scrollTo(0, 0);
    const progress = $('#generationProgress');
    if (progress) progress.style.width = '0%';
    $('#generateManualBtn').disabled = false;
    $('#exportWordBtn').hidden = true;
    ensurePauseButton();
    $('#testState').textContent = '已构建';
    $('#testResultTitle').textContent = `${nodes.length} 个组件，${connections.length} 条连线`;
    $('#testResultText').textContent = `已保存独立测试项目：${manifest.headings.length} 个原文标题、${manifest.screenshots.length} 张真实截图。`;
    toast('真实操作手册案例已保存到数据库');
  } catch (error) {
    if (project?.id && !committed) {
      try { await api(`/copyrights/${project.id}`, { method: 'DELETE' }); } catch { /* Keep the original import error. */ }
    }
    $('#testState').textContent = '导入失败';
    $('#testResultText').textContent = error.message;
    toast(error.message || '真实案例导入失败', 'error');
  } finally {
    button.disabled = false;
    button.textContent = original;
    $('#testFillFoundationBtn').disabled = false;
  }
}

function fillTestFoundation() {
  profile = { ...testCaseProfile };
  renderProfile();
  saveWorkspace();
  $('#testState').textContent = '已填写';
  $('#testResultTitle').textContent = '基础信息已完整';
  $('#testResultText').textContent = '医疗影像运维管理系统 V1.0 的真实案例字段已写入当前工作区。';
  toast('测试基础信息已填写');
  switchView('foundation');
}

$('#testFillFoundationBtn').addEventListener('click', fillTestFoundation);
$('#testBuildManualBtn').addEventListener('click', buildTestManual);
