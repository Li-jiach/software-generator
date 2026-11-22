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
  firstPublishDate: ['首次发表日期'],
  modificationDetails: ['修改说明'],
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
  otherLanguages: ['其他编程语言'],
  sourceLines: ['源程序量（行）', '源程序量', '源程序行数'],
  purpose: ['开发目的'],
  industry: ['面向领域/行业', '面向行业/领域', '面向领域', '面向行业'],
  mainFunction: ['软件的主要功能', '软件主要功能', '主要功能'],
  technicalFeatures: ['软件的技术特点', '软件技术特点', '技术特点'],
  technicalTags: ['软件的技术特点', '软件技术特点', '技术特点']
}

export const stages = {
  application: ['acquisition', 'fullName', 'shortName', 'version', 'rights'],
  development: ['softwareType', 'descriptionType', 'devMode', 'devFinish', 'publishStatus', 'firstPublishDate', 'modificationDetails', 'copyrightOwner', 'originalCopies', 'duplicateCopies'],
  features: ['developmentHardware', 'runtimeHardware', 'devOS', 'devTools', 'runtimeOS', 'supportSoftware', 'languages', 'otherLanguages', 'sourceLines', 'purpose', 'industry', 'mainFunction', 'technicalFeatures', 'technicalTags']
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
  const editable = node => node && !node.disabled && !node.matches('input[type=password],.disabled,.disabled input') && node.getAttribute('aria-disabled') !== 'true'
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

  if (action === 'reset-login') {
    localStorage.removeItem('webUserInfo')
    localStorage.removeItem('upgradeVo')
    sessionStorage.clear()
    for (const domain of ['', '; Domain=ccopyright.com.cn']) {
      document.cookie = 'webUserInfo=; Max-Age=0; Path=/; Secure' + domain
    }
    return !document.cookie.split(';').some(cookie => cookie.trim().startsWith('webUserInfo='))
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
      if (all('.hd-dialog,[role=dialog]').length) return 'identity-blocked'
      const applicant = one(exact('我是申请人', all('h2')))
      if (!applicant || data.observingLogin || data.applicantClicked) return 'identity'
      const card = applicant.closest('.created') || applicant
      if (!editable(card) || card.matches('.disabled-1,.disabled-2')) return 'identity-blocked'
      card.click()
      return 'applicant-clicked'
    }
    if (stage === 'application' &&
        (!findControls(['软件全称', '软件名称']).length || !findControls(['版本号', '软件版本号', '软件版本']).length))
      return 'form-loading'
    if (stage === 'development' && !findControls(['软件分类','软件类型'],'softwareType').length &&
        !findControls(['开发完成日期','开发完成时间'],'devFinish').length) return 'form-loading'
    if (stage === 'confirm' && !exact('确认填报', all('button,[role=button]')).length) return 'form-loading'
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

  if (action === 'material') {
    if (stage !== data.stage) return {state:'changed'}
    const heading = one(all(data.slot === 'ownership' && stage !== 'features' ? 'p' : 'h3,span')
      .filter(node => !node.children.length && normalize(node.textContent) === normalize(data.label) &&
        node.closest('.fillin_item')))
    const direct = data.slot === 'ownership' && stage !== 'features'
      ? one(all('.hdUpload p').filter(node => normalize(node.textContent) === normalize(data.label)))
      : null
    const group = direct?.closest('.upLoadBox') || heading?.closest('.fillin_item')
    if (!group) return {state:'unavailable'}
    if (stage === 'features' && ['source','manual'].includes(data.slot)) {
      const radio = one([...group.querySelectorAll('input[type=radio]')].filter(node =>
        [...node.labels || []].some(label => normalize(label.querySelector('.radio-inner')?.textContent || label.textContent) === data.deposit)))
      if (radio && !radio.checked) {
        if (!editable(radio)) return {state:'unavailable'}
        ([...radio.labels][0] || radio).click()
        return {state:'setting'}
      }
      if (data.deposit === '例外交存') {
        const combo = one(all('.hd-select > .box', group))
        if (!radio || !data.method || !combo) return {state:'unavailable'}
        if (normalize(combo.innerText || combo.querySelector('input')?.value) !== normalize(data.method)) {
          const option = one(exact(data.method, all('.hd-option,[role=option]')))
          if (option) option.click()
          else combo.click()
          return {state:'setting'}
        }
        if (data.method === '使用黑色宽斜线覆盖') {
          const pages = one(all('input[placeholder="请输入页码"]',group))
          if (!data.pages || !editable(pages)) return {state:'unavailable'}
          if (pages.value !== data.pages && !setValue(pages,data.pages)) return {state:'unavailable'}
        }
      }
    }
    const uploads = all('.hdUpload', group).filter(upload => !upload.parentElement.closest('.hdUpload'))
    // The portal's upload trigger is styled as a card but contains the file picker.
    const cards = uploads.flatMap(upload => all('.hdUpload-item,.hdUpload-showFile-item', upload))
      .filter(card => !card.matches('.hdUpload-imgBtn') && !card.querySelector('input[type=file]'))
    const matches = cards.filter(card => all('.pdfName,.hdUpload-showFile-name', card)
      .some(name => name.textContent.trim() === data.name))
    if (matches.some(card => card.querySelector('.statusSvg.error,.hdUpload-showFile-item svg.error'))) return {state:'failed'}
    if (matches.length && cards.length === matches.length &&
        matches.every(card => !card.querySelector('.hdUpload-item-progressLoop:not(.hidden),.progress') &&
          (!card.querySelector('.statusSvg') || card.querySelector('.statusSvg.over'))))
      return {state:'uploaded'}
    if (cards.some(card => card.querySelector('.hdUpload-item-progressLoop:not(.hidden),.progress'))) return {state:'uploading'}
    if (cards.length) return {state:'existing'}
    if (!data.file) return {state:'empty'}
    const input = one(uploads.flatMap(upload => [...upload.querySelectorAll('input[type=file]:not(:disabled)')]))
    if (!input) return {state:'unavailable'}
    const transfer = new DataTransfer()
    transfer.items.add(new File([data.file], data.name, {type:'application/pdf'}))
    input.files = transfer.files
    input.dispatchEvent(new Event('change', {bubbles:true}))
    return {state:'started'}
  }

  if (action === 'inspect-confirm') {
    if (stage !== 'confirm') return null
    const names = all('.material_list td,.material_list td p,.hd_img p,.pdfName,.hdUpload-showFile-name').map(node => node.textContent.trim())
    const confirm = one(exact('确认填报', all('button,[role=button]')))
    const pageCounts = all('.material_list input:not([type=hidden]):not(:disabled)')
    return {
      missing: data.materials.filter(file => !names.includes(file.name) && !(file.summaryLabel && names.includes(file.summaryLabel))).map(file => file.label),
      pageCountsMissing: pageCounts.some(input => !/^\d+$/.test(input.value) || Number(input.value) < 1),
      ready: Boolean(confirm && editable(confirm) && confirm.getAttribute('aria-disabled') !== 'true'),
    }
  }

  function fieldGroups(labels) {
    const names = labels.map(normalize)
    return all('h3, h4, label, legend, th, dt, .el-form-item__label, .ant-form-item-label, .ivu-form-item-label, span')
      .filter(node => names.includes(normalize(node.textContent)))
      .map(label => ({
        direct: label.control,
        group: label.closest('.fillin_item_left,.fillin_item,.el-form-item,.ant-form-item,.ivu-form-item,tr,fieldset') || label.parentElement
      }))
  }
  function findControls(labels, field) {
    if (field === 'otherLanguages') return all('textarea[placeholder^="若有需要，请输入其他编程语言"]')

    for (const {direct, group} of fieldGroups(labels)) {
      if (direct && visible(direct) && !['radio','checkbox'].includes(direct.type)) return [direct]
      const inputs = [...group.querySelectorAll(controls)].filter(node =>
        visible(node) || ['radio','checkbox'].includes(node.type) && [...node.labels || []].some(visible)
      )
      if (field === 'technicalFeatures') return inputs.filter(node => node.tagName === 'TEXTAREA')
      if (['languages','technicalTags'].includes(field)) return inputs.filter(node => node.type === 'checkbox')
      if (inputs.length === 1 || inputs.length && inputs.every(node => ['radio','checkbox'].includes(node.type))) return inputs
      const select = one(all('.hd-select > .box', group))
      if (select) return [select]
    }
    const names = labels.map(normalize)
    const inputs = all(controls).filter(node => names.some(name => {
      const placeholder = normalize(node.placeholder || node.getAttribute('aria-label'))
      return [name, '请输入' + name, '请选择' + name].includes(placeholder)
    }))
    if (field === 'modificationDetails') return all('textarea[placeholder^="修改合成或翻译说明"]')
    if (field === 'originalCopies' && stage === 'development') return all('input[placeholder="请输入委托事项"]')
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
        all('span,div,input,td,p', group).some(node => !node.children.length && normalize(node.value || node.textContent) === normalize(value))
      )
      if (match) filled.push(field)
      continue
    }
    const inputs = findControls(labels[field], field)
    if (!inputs.length) continue
    const [node] = inputs
    const choices = ['languages','technicalTags'].includes(field) ? value.split(/[,，、]/).map(v => v.trim()).filter(Boolean) : [value]
    const nameOf = option => normalize([...option.labels || []]
      .map(label => label.querySelector('.radio-inner,.checkbox-inner')?.textContent || label.textContent).join(' ') || option.value)
    if (node.type === 'radio' || node.type === 'checkbox') {
      const options = choices.map(choice => one(inputs.filter(option => editable(option) && nameOf(option) === normalize(choice))))
      if (options.every(Boolean)) {
        if (node.type === 'checkbox') {
          for (const option of inputs) {
            if (option.checked && editable(option) && !options.includes(option))
              ([...option.labels || []].find(visible) || option).click()
          }
        }
        options.forEach(option => {
          if (!option.checked) ([...option.labels || []].find(visible) || option).click()
        })
        if (inputs.every(option => option.checked === options.includes(option))) filled.push(field)
      }
    } else if (node.value === value || ['devFinish','firstPublishDate'].includes(field) && node.value?.replaceAll('/', '-') === value) {
      filled.push(field)
    } else if (!editable(node)) {
      continue
    } else if (['devFinish','firstPublishDate'].includes(field) && node.readOnly && chooseDate(node, value)) {
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
        const options = combo.matches('.hd-select') ? all('.hd-option', combo) :
          all('[role=option],.el-select-dropdown__item,.ant-select-item-option,.ivu-select-item')
        const next = choices.find(choice => !exact(choice, selected).length)
        const option = one(exact(next, options))
        if (option) option.click()
        else if (!options.length && !all('.dropdown', combo).length) node.click()
        return {filled, pending: true}
      }
    } else if (!node.readOnly && (node.maxLength < 0 || value.length <= node.maxLength)) {
      if (stage === 'application' && ['fullName','shortName','version'].includes(field)) {
        // R11 saves these values on blur. Commit each field before touching the next one.
        node.focus()
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node,value)
        node.dispatchEvent(new Event('input',{bubbles:true}))
        node.dispatchEvent(new Event('change',{bubbles:true}))
        node.blur()
        return {filled,pending:true}
      }
      if (setValue(node, value)) filled.push(field)
    }
  }
  return {filled}
}

// The official tab exchanges one action at a time with its workbench opener.
function runPortalStep(workbench, viewer, act) {
  if (location.origin !== 'https://register.ccopyright.com.cn') return 'waiting'
  if (!window.opener || window.opener.closed) return 'done'
  return new Promise(resolve => {
    const channel = new MessageChannel()
    const timer = setTimeout(() => finish('waiting'), 3500)
    function finish(state) {
      clearTimeout(timer)
      channel.port1.close()
      resolve(state)
    }
    channel.port1.onmessage = ({data}) => {
      if (data.done || data.idle) {
        finish(data.done ? 'done' : 'waiting')
        return
      }
      try {
        channel.port1.postMessage({result: act(data.action, data.input)})
      } catch {
        channel.port1.postMessage({error:true})
      } finally {
        finish('running')
      }
    }
    window.opener.postMessage({type:'official-portal-step', viewer}, workbench, [channel.port2])
  })
}

export function officialMacro(project, ticket, viewer, origin, resetSession = false) {
  const boot = JSON.stringify({project, ticket, viewer})
  const evaluatePortal = 'return (' + runPortalStep + ')(' + JSON.stringify(origin) + ',' +
    JSON.stringify(viewer) + ',' + portal + ');'
  const entryUrl = resetSession ? portalOrigin + '/registration.html#/registerSoft' : loginUrl
  const popupStart = 'if (location.origin === ' + JSON.stringify(origin) +
    ' && window.opener) { window.opener.postMessage({type:"official-popup-start",viewer:' +
    JSON.stringify(viewer) + '},location.origin); setTimeout(() => location.replace(' + JSON.stringify(entryUrl) + '), 400); } return true;'
  const command = (Command, Target = '', Value = '') => ({Command, Target, Value})
  return {
    Name: 'Copyright_R11_Fill',
    Commands: [
      command('selectWindow', 'title=官网自动申报 · ' + viewer.slice(0, 8)),
      command('waitForElementPresent', `css=#official-live[data-official-view="${viewer}"]`),
      command('executeScript', 'window.dispatchEvent(new CustomEvent("copyrightStartOfficial",{detail:' + boot + '}));return true;', 'officialStarted'),
      command('store', '100', '!timeout_wait'),
      command('waitForElementPresent', `css=#official-live[data-official-view="${viewer}"][data-official-state="ready"]`),
      command('store', '10', '!timeout_wait'),
      command('selectWindow', 'title=官网申报窗口 · ' + viewer.slice(0, 8)),
      command('executeScript', popupStart, 'officialPopupStarted'),
      command('store', 'waiting', 'officialStep'),
      command('store', '0', 'officialPolls'),
      command('while', '${officialStep} !== "done" && Number(${officialPolls}) < 450'),
      command('store', 'true', '!errorIgnore'),
      command('executeScript', evaluatePortal, 'officialStep'),
      command('store', 'false', '!errorIgnore'),
      command('executeScript_Sandbox', 'return Number(${officialPolls}) + 1;', 'officialPolls'),
      command('pause', '700'),
      command('end')
    ]
  }
}
