export const portalOrigin = 'https://register.ccopyright.com.cn'
export const loginUrl = portalOrigin + '/login.html'

export const fieldMap = {
  acquisition: ['权利取得方式'],
  fullName: ['软件全称', '软件名称'],
  shortName: ['软件简称', '简称'],
  version: ['版本号', '软件版本号', '软件版本'],
  rights: ['权利范围'],
  softwareType: ['软件分类', '软件类型'],
  descriptionType: ['软件作品说明', '软件说明'],
  devMode: ['开发方式'],
  devFinish: ['开发完成日期', '开发完成时间'],
  publishStatus: ['发表状态', '发表情况', '是否发表'],
  copyrightOwner: ['著作权人名称', '著作权人姓名', '著作权人'],
  originalCopies: ['证书正本数量', '正本数量'],
  duplicateCopies: ['证书副本数量', '副本数量'],
  developmentHardware: ['开发的硬件环境', '开发硬件环境'],
  runtimeHardware: ['运行的硬件环境', '运行硬件环境'],
  devOS: ['开发该软件的操作系统', '开发操作系统'],
  devTools: ['软件开发环境/开发工具', '开发环境/开发工具', '软件开发环境', '开发工具'],
  runtimeOS: ['该软件的运行平台/操作系统', '软件运行平台/操作系统', '运行平台/操作系统', '运行操作系统'],
  supportSoftware: ['软件运行支撑环境/支持软件', '运行支撑环境/支持软件', '运行支撑环境'],
  languages: ['编程语言'],
  sourceLines: ['源程序量（行）', '源程序量', '源程序行数'],
  purpose: ['开发目的'],
  industry: ['面向领域/行业', '面向行业/领域', '面向领域', '面向行业'],
  mainFunction: ['软件的主要功能', '软件主要功能', '主要功能'],
  technicalFeatures: ['软件的技术特点', '软件技术特点', '技术特点']
}

export const stages = {
  application: ['acquisition', 'fullName', 'shortName', 'version', 'rights'],
  development: ['softwareType', 'descriptionType', 'devMode', 'devFinish', 'publishStatus', 'copyrightOwner', 'originalCopies', 'duplicateCopies'],
  features: ['developmentHardware', 'runtimeHardware', 'devOS', 'devTools', 'runtimeOS', 'supportSoftware', 'languages', 'sourceLines', 'purpose', 'industry', 'mainFunction', 'technicalFeatures']
}

// This function is evaluated by Ui.Vision in the current tab.
export function portal(action, data) {
  if (location.origin !== 'https://register.ccopyright.com.cn') return null

  const normalize = text => String(text ?? '').replace(/[\s*：:]/g, '').replace(/\(/g, '（').replace(/\)/g, '）')
  const visible = node => node && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden'
  const all = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible)
  const exact = (label, nodes) => nodes.filter(node => normalize(node.textContent) === normalize(label))
  const one = nodes => nodes.length === 1 ? nodes[0] : null
  const leaf = (label,root=document) => one(exact(label, all('button,a,label,li,span,div',root).filter(n => !n.children.length)))
  const controls = 'input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=file]), textarea, select'
  const editable = node => node && !node.disabled && !node.matches('input[type=password],.disabled,.disabled input')
  const stage = location.pathname === '/r11.html' && location.hash.match(/^#\/([a-z]+)/)?.[1]
  const inlineLogin = () => all('.lg_hd_dialog_warp .hd-dialog')[0] || null
  // Only inspect whether the portal can read its own cookie.
  const missingSession = () => {
    try {
      return typeof window.getCookie === 'function' && !window.getCookie()
    } catch {
      return true
    }
  }
  const setValue = (node, value) => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), 'value').set.call(node, value)
    node.dispatchEvent(new Event('input', {bubbles: true}))
    node.dispatchEvent(new Event('change', {bubbles: true}))
    node.dispatchEvent(new FocusEvent('blur', {bubbles: true}))
    return node.value === value
  }

  if (action === 'navigate') {
    if ((location.pathname === '/login.html' || inlineLogin()) &&
        all('.hd-message, [role=alert], .hd-dialog').some(node => /网络(?:异常|错误|连接失败)/.test(normalize(node.textContent))))
      return 'login-network-error'
    if (location.pathname === '/login.html') return 'login'
    if (location.pathname === '/account.html') {
      if (document.readyState !== 'complete') return 'waiting'
      return missingSession() ? 'registration-session-missing' : 'home'
    }
    if (stage === 'identity') {
      const applicant = one(exact('我是申请人', all('h2')))
      if (applicant && !data.observingLogin) applicant.click()
      return 'identity'
    }
    if (stage === 'application' &&
        (!findControls(['软件全称', '软件名称']).length || !findControls(['版本号', '软件版本号', '软件版本']).length))
      return 'form-loading'
    if (['application','development','features','confirm'].includes(stage)) return stage
    if (!location.hash.startsWith('#/registerSoft')) {
      if (location.hash === '#/index' && !data.observingLogin && leaf('跳过')) {
        leaf('跳过').click()
        return 'guide'
      }
      if (location.hash === '#/index') return 'home'
      return 'waiting'
    }
    if (inlineLogin()) return 'inline-login'
    if (all('.hd-dialog, [role=dialog]').length) return 'registration-dialog'
    if (missingSession()) return 'registration-session-missing'
    const cards = all('.register-soft .link-box, td').filter(card =>
      exact('R11', all('.img-box',card)).length ||
      exact('计算机软件著作权登记申请',all('h1,h2,h3,h4',card)).length
    )
    const entry = one([...new Set(cards.flatMap(card => exact('立即登记',all('button',card))))])
    if (!entry || entry.disabled) return 'registration-unavailable'
    if (data.waitForEntry || data.observingLogin) return 'registration-wait'
    entry.click()
    return 'opened'
  }

  if (action === 'registration-list') {
    if (location.pathname !== '/account.html' &&
        !(location.pathname === '/registration.html' && location.hash === '#/index')) return false
    location.assign('/registration.html#/registerSoft')
    return true
  }

  if (action === 'login') {
    const root = location.pathname === '/login.html' ? document : inlineLogin()
    if (!root) return false
    if (data.stage === 'organization') {
      const organization = leaf('机构',root) || leaf('机构用户',root)
      if (!organization) return false
      organization.click()
      return true
    }
    if (data.stage === 'administrator') {
      const administrator = leaf('管理员',root) || leaf('机构管理员',root)
      if (!administrator) return false
      administrator.click()
      return true
    }
    if (data.stage === 'password-mode') {
      const passwordLogin = leaf('密码登录',root)
      if (!passwordLogin) return false
      passwordLogin.click()
      return true
    }
    const password = one(all('input[type=password]',root))
    const account = one(all('input',root).filter(node => /用户名|账号|手机号|邮箱/.test(node.placeholder)))
    const submit = one(exact('立即登录', all('button',root)))
    if (!password || !account || !submit) return false
    return setValue(account, data.username) && setValue(password, data.password) && (submit.click(), true)
  }

  if (action === 'advance') {
    if (stage !== data.stage || !['application','development'].includes(stage)) return false
    const next = one(exact('下一步', all('button')))
    if (!next || next.disabled) return false
    next.click()
    return true
  }

  function fieldGroups(labels) {
    const names = labels.map(normalize)
    return all('h3, h4, label, legend, th, dt, .el-form-item__label, .ant-form-item-label, .ivu-form-item-label, span')
      .filter(node => names.includes(normalize(node.textContent)))
      .map(label => ({
        direct: label.control,
        group: label.closest('.fillin_item,.el-form-item,.ant-form-item,.ivu-form-item,tr,fieldset') || label.parentElement
      }))
  }
  function findControls(labels, field) {
    for (const {direct, group} of fieldGroups(labels)) {
      if (direct && visible(direct) && !['radio','checkbox'].includes(direct.type)) return [direct]
      const inputs = [...group.querySelectorAll(controls)].filter(node =>
        visible(node) || ['radio','checkbox'].includes(node.type) && [...node.labels || []].some(visible)
      )
      if (field === 'technicalFeatures') return inputs.filter(node => node.tagName === 'TEXTAREA')
      if (field === 'languages') return inputs.filter(node => node.type === 'checkbox')
      if (inputs.length === 1 || inputs.length && inputs.every(node => ['radio','checkbox'].includes(node.type))) return inputs
      const select = one(all('.hd-select > .box', group))
      if (select) return [select]
    }
    const names = labels.map(normalize)
    const inputs = all(controls).filter(node => names.some(name => {
      const placeholder = normalize(node.placeholder || node.getAttribute('aria-label'))
      return [name, '请输入' + name, '请选择' + name].includes(placeholder)
    }))
    if (field === 'originalCopies' && stage === 'development') return all('input[placeholder="请输入委托事项"][disabled]')
    return inputs.length === 1 ? inputs : []
  }

  function chooseDate(node, value) {
    const [year, month, day] = value.split('-').map(Number)
    if (!year || !month || !day) return false
    const input = node.closest('.datepicker-input')
    const panel = input?.parentElement.querySelector('.datepicker-main')
    if (!panel) return false
    if (!panel.classList.contains('open')) {
      input.click()
      return true
    }
    const [yearSelect, monthSelect] = all('.datePickerSelect', panel)
    if (!yearSelect || !monthSelect) return false
    for (const [selector, label] of [[yearSelect, year + '年'], [monthSelect, month + '月']]) {
      const text = selector.querySelector('.datePickerSelectText')
      if (normalize(text?.textContent) === label) continue
      const choice = one(exact(label, all('.datePickerSelectMenu .menu', selector)))
      if (choice) choice.click()
      else text?.click()
      return true
    }
    const date = one(exact(String(day), all('tbody td:not(.disabled)', panel)))
    date?.click()
    return Boolean(date)
  }

  if (stage !== data.stage) return null
  const {values, labels} = data
  const fullName = findControls(labels.fullName)[0]
  const version = findControls(labels.version)[0]
  if (stage === 'application' &&
      ((fullName?.value && values.fullName && fullName.value !== values.fullName) ||
       (version?.value && values.version && version.value !== values.version))) return {conflict: true}

  const filled = []
  for (const [field, value] of Object.entries(values)) {
    if (!value) continue
    if (field === 'copyrightOwner') {
      const match = fieldGroups(labels[field]).some(({group}) =>
        all('span,div,input', group).some(node => !node.children.length && normalize(node.value || node.textContent) === normalize(value))
      )
      if (match) filled.push(field)
      continue
    }
    const inputs = findControls(labels[field], field)
    if (!inputs.length) continue
    const [node] = inputs
    const choices = field === 'languages' ? value.split(/[,，、]/).map(v => v.trim()).filter(Boolean) : [value]
    const nameOf = option => normalize([...option.labels || []]
      .map(label => label.querySelector('.radio-inner,.checkbox-inner')?.textContent || label.textContent).join(' ') || option.value)
    if (node.type === 'radio' || node.type === 'checkbox') {
      const options = choices.map(choice => one(inputs.filter(option => editable(option) && nameOf(option) === normalize(choice))))
      if (options.every(Boolean)) {
        options.forEach(option => {
          if (!option.checked) ([...option.labels || []].find(visible) || option).click()
        })
        if (options.every(option => option.checked)) filled.push(field)
      }
    } else if (node.value === value || field === 'devFinish' && node.value?.replaceAll('/', '-') === value) {
      filled.push(field)
    } else if (!editable(node)) {
      continue
    } else if (field === 'devFinish' && node.readOnly && chooseDate(node, value)) {
      return {filled, pending: true}
    } else if (node instanceof HTMLSelectElement) {
      const options = choices.map(choice => one([...node.options].filter(option => normalize(option.label) === normalize(choice))))
      if (options.every(Boolean) && (node.multiple || options.length === 1)) {
        for (const option of node.options) option.selected = options.includes(option)
        node.dispatchEvent(new Event('change', {bubbles: true}))
        filled.push(field)
      }
    } else if (node.closest('.hd-select,[role=combobox],.el-select,.ant-select,.ivu-select')) {
      const combo = node.closest('.hd-select,[role=combobox],.el-select,.ant-select,.ivu-select')
      const selected = all('.el-tag__content,.ant-select-selection-item,.ivu-tag-text', combo)
      if (choices.every(choice => normalize(node.value) === normalize(choice) || exact(choice, selected).length === 1 || normalize(node.innerText) === normalize(choice))) {
        filled.push(field)
      } else {
        const options = all('.hd-option,[role=option],.el-select-dropdown__item,.ant-select-item-option,.ivu-select-item')
        const next = choices.find(choice => !exact(choice, selected).length)
        const option = one(exact(next, options))
        if (option) option.click()
        else if (!options.length) node.click()
        return {filled, pending: true}
      }
    } else if (!node.readOnly && (node.maxLength < 0 || value.length <= node.maxLength) && setValue(node, value)) {
      filled.push(field)
    }
  }
  return {filled}
}

// The official frame receives its next action over a one-use MessageChannel.
function runFrameStep(workbench, viewer, act) {
  if (location.origin !== 'https://register.ccopyright.com.cn' || window.parent === window) return false
  const channel = new MessageChannel()
  const timeout = setTimeout(() => channel.port1.close(), 3000)
  channel.port1.onmessage = ({data}) => {
    clearTimeout(timeout)
    try {
      channel.port1.postMessage({result: act(data.action, data.input)})
    } catch {
      channel.port1.postMessage({error: true})
    } finally {
      channel.port1.close()
    }
  }
  window.parent.postMessage({type:'official-frame-step', viewer}, workbench, [channel.port2])
  return true
}

export function officialMacro(project, ticket, viewer, origin) {
  const boot = JSON.stringify({project, ticket, viewer})
  const evaluateFrame = 'return (' + runFrameStep + ')(' + JSON.stringify(origin) + ',' +
    JSON.stringify(viewer) + ',' + portal + ');'
  const command = (Command, Target = '', Value = '') => ({Command, Target, Value})
  return {
    Name: 'Copyright_R11_Fill',
    Commands: [
      command('selectWindow', 'title=官网自动申报 · ' + viewer.slice(0, 8)),
      command('waitForElementPresent', `css=#official-live[data-official-view="${viewer}"]`),
      command('executeScript', 'window.dispatchEvent(new CustomEvent("copyrightStartOfficial",{detail:' + boot + '}));return true;', 'officialStarted'),
      command('store', 'starting', 'officialState'),
      command('while', '${officialState} !== "done"'),
      command('selectFrame', 'relative=top'),
      command('executeScript', 'const panel = document.getElementById("official-live"); return panel?.dataset.officialView === ' + JSON.stringify(viewer) + ' ? panel.dataset.officialState : "done";', 'officialState'),
      command('if', '${officialState} === "running"'),
      command('store', 'true', '!errorIgnore'),
      command('selectFrame', 'id=official-browser'),
      command('executeScript', evaluateFrame, 'officialStep'),
      command('store', 'false', '!errorIgnore'),
      command('end'),
      command('pause', '700'),
      command('end')
    ]
  }
}
