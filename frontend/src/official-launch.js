import {fieldMap, loginUrl, officialMacro, portalOrigin, stages} from './official-macro.js'

const resetKey = 'copyright-official-reset-session'

export function markOfficialSessionReset() {
  sessionStorage.setItem(resetKey, 'pending')
}

export function startOfficialViewer({project, ticket, panel, viewer, onStatus, onFinish}) {
  const resetSession = Boolean(sessionStorage.getItem(resetKey))
  const controller = new AbortController()
  const signal = controller.signal
  const previousTitle = document.title
  const title = '官网自动申报 · ' + viewer.slice(0, 8)
  document.title = title
  panel.dataset.officialView = viewer
  panel.dataset.officialState = 'starting'

  let request
  let deadline
  let loginDelay
  let login = {}
  let values = {}
  let materials = {}
  let uploadQueue = []
  let uploadStartedAt = 0
  let depositAttempts = 0
  let materialIssues = []
  const uploaded = new Map()
  const materialLabels = {source:'程序鉴别材料', manual:'文档鉴别材料', ownership:'其他相关证明文件'}
  let entryAttempts = 0
  let entryRetryAt = 0
  let returnedHome = false
  let attemptedLogin = false
  let applicantClicked = false
  let resumedRegistration = false
  let waitingForLogin = false
  let loginNetworkError = false
  let navigationRevision = 0
  let popup
  let popupMonitor
  let launchState = 'starting'
  let currentStage
  let expectedStage = 'application'
  let remaining
  let attempts

  function show(text, url) {
    if (url) popup.location.replace(url)
    onStatus(text, loginNetworkError, launchState)
  }

  function finish(text, state = 'done') {
    launchState = state
    dispose()
    show(text)
    onFinish()
  }

  function waitForOperator() {
    clearTimeout(deadline)
    deadline = setTimeout(() => finish('等待官网超时。你可以继续手动操作官网，或回工作台重新启动。'), 300000)
  }

  function navigate() {
    const waitForEntry = entryAttempts >= 2 || Date.now() < entryRetryAt
    request = {action:'navigate', input:{waitForEntry,observingLogin:waitingForLogin,applicantClicked}, next:onNavigation}
  }

  function onNavigation(state) {
    if (state === 'login-network-error') {
      loginNetworkError = true
      show('官网登录提示网络错误。可重新加载官网登录页，再手动登录。')
      navigate()
      return
    }
    if (loginNetworkError && state !== 'login' && state !== 'inline-login' && state !== 'waiting')
      loginNetworkError = false
    if (waitingForLogin && ['home','registration-wait','registration-unavailable','registration-session-missing','identity',
        'form-loading','application','development','features','confirm'].includes(state)) {
      waitingForLogin = false
      resumedRegistration = true
      show('已离开官网登录页，等待 5 秒后检查申报页面。')
      waitForOperator()
      loginDelay = setTimeout(navigate, 5000)
      return
    }
    if (state === 'opened') {
      if (attemptedLogin) resumedRegistration = true
      entryAttempts++
      entryRetryAt = Date.now() + 5000
      show('已点击 R11「立即登记」，正在等待官网进入申请页。')
    }
    if (state === 'registration-wait' && entryAttempts >= 2 && Date.now() >= entryRetryAt)
      show('官网仍停在软件登记列表。请处理官网窗口中的提示，或手动点击 R11「立即登记」，宏会等待申请页。')
    if (state === 'registration-session-missing' || (resumedRegistration && ['login', 'inline-login'].includes(state))) {
      finish(state === 'registration-session-missing'
        ? '官网未读取到登录会话，自动填报已暂停。请在官网窗口检查登录状态，再继续 R11 登记。'
        : '官网在进入 R11 时再次要求登录，自动填报已暂停。请在官网窗口检查登录状态，再继续 R11 登记。')
      return
    }
    if (state === 'registration-unavailable')
      show('正在等待官网启用 R11「立即登记」。若按钮持续灰色，请查看官网提示。')
    if (state === 'registration-dialog')
      show('官网弹出了登记提示。请在官网查看并处理，宏会等待进入申请页。')
    if (state === 'form-loading') show('已进入 R11，正在等待申请表加载。')
    if (state === 'home' && !returnedHome) {
      returnedHome = true
      resumedRegistration = attemptedLogin
      show('正在从官网用户中心进入软件登记。')
      request = {action:'registration-list', input:{}, next:navigate}
      return
    }
    if (state === 'home' && resumedRegistration) {
      show('已进入官网用户中心。请在官网选择「版权登记 → 软件登记」，宏会继续。')
    }
    if (state === 'login' || state === 'inline-login') {
      if (!waitingForLogin) waitForOperator()
      waitingForLogin = true
      expectedStage = 'application'
      entryAttempts = 0
      entryRetryAt = 0
      if (attemptedLogin) {
        if (loginNetworkError) {
          navigate()
          return
        }
        show('官网正在等待登录或安全验证，请在官网继续操作。')
        navigate()
        return
      }
      attemptedLogin = true
      returnedHome = false
      show('若官网要求登录或安全验证，请直接在官网操作。')
      if (login.username) loginStep('organization')
      else navigate()
      return
    }
    if (state === 'applicant-clicked') {
      applicantClicked = true
      show('已点击「我是申请人」，等待官网打开申请信息页。')
    }
    if (state === 'identity-blocked') show('官网暂未进入申请信息页。请处理当前窗口的提示。')
    if (state === expectedStage && Object.hasOwn(stages,state)) {
      waitingForLogin = false
      currentStage = state
      const names = {application:'软件申请信息',development:'软件开发信息',features:'软件功能与特点'}
      show('正在填写' + names[state] + '。')
      remaining = Object.fromEntries(stages[state].filter(key => values[key]).map(key => [key, values[key]]))
      attempts = 0
      fill()
      waitForOperator()
      return
    }
    if (state === 'confirm') {
      request = {action:'inspect-confirm', input:{
        materials: Object.entries(materials).map(([slot, file])=>({
          name:file.name.replace(/\.[^.]+$/, '') + '.pdf',
          label:materialLabels[slot],
          summaryLabel:slot === 'ownership' && uploaded.get(slot) !== materialLabels.ownership
            ? uploaded.get(slot) : undefined
        }))
      }, next:result=>{
        if (!result) { navigate(); return }
        if (result.missing.length || result.pageCountsMissing || !result.ready ||
            Object.keys(materialLabels).some(slot=>!uploaded.has(slot))) {
          const missing = result.missing.length ? '材料清单未匹配：' + result.missing.join('、') + '。' : ''
          finish('已到官网确认页。' + missing + '请核对材料清单、页数和官网必填项，再确认填报。')
          return
        }
        finish('信息和附件已填至官网确认页。请核对后手动点击「确认填报」。')
      }}
      return
    }
    navigate()
  }

  function loginStep(stage) {
    const input = stage === 'submit' ? {stage,...login} : {stage}
    if (stage === 'submit') login = {}
    request = {action:'login', input, next:result=>{
      const steps = {organization:'administrator',administrator:'password-mode','password-mode':'submit'}
      if (result && steps[stage]) loginStep(steps[stage])
      else {
        login = {}
        navigate()
      }
    }}
  }

  function fill() {
    if (!Object.keys(remaining).length) {
      completeStage()
      return
    }
    request = {action:'fill', input:{stage:currentStage,values:remaining,labels:fieldMap}, next:result=>{
      if (!result) {
        navigate()
        return
      }
      if (result.conflict) {
        finish('官网表单已有不同的软件名称或版本，请先核对。')
        return
      }
      for (const key of result.filled) delete remaining[key]
      if (++attempts < 30 && (result.pending || result.filled.length)) fill()
      else completeStage()
    }}
  }

  function completeStage() {
    const missing = Object.keys(remaining).map(key => fieldMap[key][0])
    if (missing.length) {
      expectedStage = {application:'development',development:'features',features:'confirm'}[currentStage]
      show('请在官网补充以下项目，再继续：' + missing.join('、'))
      if (currentStage === 'features') {
        // Still attach approved files on this page while the operator completes the remaining fields.
        prepareUploads(missing)
      } else {
        navigate()
      }
      return
    }
    if (currentStage === 'features') {
      prepareUploads([])
      return
    }
    if (currentStage === 'application' && values.rights === '部分权利' && materials.ownership) {
      uploadQueue = [{slot:'ownership',label:'权利范围相关文件'}]
      uploadNext(()=>waitForNext())
      return
    }
    const contract = {'合作开发':'合作开发合同或协议','委托开发':'委托开发合同或协议','下达任务开发':'项目任务书或合同'}[values.devMode]
    if (currentStage === 'development' && contract && materials.ownership && !uploaded.has('ownership') &&
        values.rights !== '部分权利' && values.acquisition !== '继受取得' && values.descriptionType === '原创') {
      uploadQueue = [{slot:'ownership',label:contract}]
      uploadNext(()=>waitForNext())
      return
    }
    waitForNext()
  }

  function waitForNext() {
    expectedStage = {application:'development',development:'features',features:'confirm'}[currentStage]
    waitForOperator()
    show(materialIssues.length
      ? materialIssues.join('。') + '。请补齐后手动点击「下一步」。'
      : '本页填写完成。请核对后手动点击「下一步」。')
    navigate()
  }

  function prepareUploads(missing) {
    uploadQueue = Object.entries(materialLabels)
      .filter(([slot])=>!uploaded.has(slot))
      .map(([slot,label])=>({slot,label}))
    uploadNext(()=>{
      if (missing.length) {
        materialIssues.push('请补充：' + missing.join('、'))
        waitForNext()
      } else {
        waitForNext()
      }
    })
  }

  function uploadNext(done) {
    if (!uploadQueue.length) {
      done()
      return
    }
    const {slot,label} = uploadQueue[0]
    function skip(reason) {
      materialIssues.push(label + '：' + reason)
      uploadQueue.shift()
      uploadStartedAt = 0
      depositAttempts = 0
      uploadNext(done)
    }
    const material = materials[slot]
    if (!material || material.size > 20 * 1024 * 1024) {
      skip('缺少可上传的已审核材料，或原件超过 20 MB')
      return
    }
    const name = material.name.replace(/\.[^.]+$/, '') + '.pdf'
    const input = {stage:currentStage,slot,label,name,deposit:values[slot+'Deposit'] || '一般交存',
      method:values[slot+'DepositMethod'], pages:values[slot+'DepositPages']}
    show('正在核对或上传' + label + '。')
    function check() {
      request = {action:'material', input, next:handle}
    }
    async function handle(result) {
      if (signal.aborted) return
      if (result?.state === 'setting' && ++depositAttempts < 8) { check(); return }
      if (result?.state === 'uploaded') {
        uploaded.set(slot, label === '项目任务书或合同' ? '下达任务的项目任务书或合同' : label)
        uploadQueue.shift()
        uploadStartedAt = 0
        depositAttempts = 0
        uploadNext(done)
        return
      }
      if (result?.state === 'started' || result?.state === 'uploading' ||
          (result?.state === 'empty' && uploadStartedAt)) {
        if (!uploadStartedAt) uploadStartedAt = Date.now()
        if (Date.now() - uploadStartedAt < 90000) { check(); return }
      } else if (result?.state === 'empty') {
        try {
          show('正在准备' + label + '的申报 PDF。')
          const response = await fetch('/api/projects/' + encodeURIComponent(project) +
            '/official-application/materials/' + slot + '/' + encodeURIComponent(material.id) +
            '/pdf?sha256=' + encodeURIComponent(material.sha256), {cache:'no-store',signal})
          if (!response.ok) {
            const error = await response.json()
            throw new Error(error.message || '附件转换或校验失败')
          }
          const file = await response.blob()
          if (new TextDecoder().decode(await file.slice(0,5).arrayBuffer()) !== '%PDF-')
            throw new Error('服务端未返回有效的 PDF')
          if (signal.aborted) return
          uploadStartedAt = Date.now()
          request = {action:'material',input:{...input,file},next:handle}
        } catch (error) {
          if (!signal.aborted) skip(error.message)
        }
        return
      }
      if (result?.state === 'changed') { navigate(); return }
      const details = {
        existing:'已有不同的文件，请核对官网这一栏的附件。',
        unavailable:'找不到可用的上传控件，请查看官网这一栏。',
        failed:'官网显示上传失败，请查看错误提示。',
        setting:'官网交存方式或页码未能设置，请核对该栏。'
      }
      skip(details[result?.state] || '等待官网确认上传超时，请查看该栏的上传状态')
    }
    check()
  }

  window.addEventListener('message', event => {
    if (panel.dataset.officialState !== 'running' || event.origin !== portalOrigin || event.source !== popup ||
        event.data?.type !== 'official-portal-step' || event.data.viewer !== viewer || !event.ports[0]) return
    const port = event.ports[0]
    if (!request) {port.postMessage({idle:true});port.close();return}
    const step = request
    const revision = navigationRevision
    request = null
    const timer = setTimeout(() => {
      port.close()
      if (signal.aborted || revision !== navigationRevision || panel.dataset.officialState !== 'running') return
      if (step.action === 'login' && step.input.stage === 'submit') navigate()
      else if (step.action === 'material' && step.input.file) {
        const {file, ...input} = step.input
        request = {...step,input}
      } else request = step
    }, 1500)
    port.onmessage = ({data}) => {
      clearTimeout(timer)
      port.close()
      if (signal.aborted || revision !== navigationRevision || panel.dataset.officialState !== 'running') return
      if (data.error) finish('Ui.Vision 无法操作当前官网控件，请在官网人工核对。')
      else step.next(data.result)
    }
    port.postMessage({action:step.action,input:step.input})
  }, {signal})

  // After completion, the popup macro gets a short window to read its stop signal.
  function stopPopupMacro(event) {
    if (event.origin !== portalOrigin || event.source !== popup ||
        event.data?.type !== 'official-portal-step' || event.data.viewer !== viewer || !event.ports[0]) return
    event.ports[0].postMessage({done:true})
    event.ports[0].close()
    window.removeEventListener('message', stopPopupMacro)
  }

  window.addEventListener('copyrightStartOfficial', async event => {
    const launch = event.detail
    if (launch?.viewer !== viewer || launch.project !== project || launch.ticket !== ticket ||
        panel.dataset.officialState !== 'starting') return
    clearTimeout(deadline)
    panel.dataset.officialState = 'loading'
    launchState = 'loading'
    show('正在检查当前审核版本。')
    try {
      const path = '/api/projects/' + encodeURIComponent(launch.project) + '/official-application/consume'
      const response = await fetch(path,{
        method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:launch.ticket}),
        cache:'no-store', signal
      })
      if (!response.ok) throw new Error('启动凭证已失效，或审核状态已变化。请回工作台重新启动。')
      const {form,login:account,materials:approved} = await response.json()
      if (signal.aborted) return
      login = account
      materials = approved || {}
      values = Object.fromEntries(Object.keys(fieldMap).filter(key=>form[key]).map(key=>[key,form[key]]))
      const hardware = (cpu,ram,disk) => [cpu&&'CPU '+cpu,ram&&'内存 '+ram,disk&&'硬盘 '+disk].filter(Boolean).join('，')
      values.developmentHardware ||= hardware(form.devCPU,form.devRAM,form.devDisk)
      values.runtimeHardware ||= hardware(form.runCPU,form.runRAM,form.runDisk)
      for (const slot of ['source','manual']) {
        for (const suffix of ['Deposit','DepositMethod','DepositPages']) values[slot+suffix] = form[slot+suffix]
      }
      if (values.descriptionType === '修改（含翻译、合成）') values.descriptionType = '修改（含翻译软件、合成软件）'
      waitingForLogin = true
      navigate()
      panel.dataset.officialState = 'awaiting-window'
      launchState = 'awaiting-window'
      show('Ui.Vision 已确认。请点击「打开申报窗口」。')
      deadline = setTimeout(() => finish('等待打开申报窗口超时。请刷新页面后重试。', 'approval-timeout'), 90000)
    } catch (error) {
      if (!signal.aborted) finish(error.message)
    }
  }, {signal})

  function dispose() {
    if (signal.aborted) return
    controller.abort()
    clearTimeout(deadline)
    clearTimeout(loginDelay)
    clearInterval(popupMonitor)
    if (popup && !popup.closed) {
      window.addEventListener('message', stopPopupMacro)
      setTimeout(() => window.removeEventListener('message', stopPopupMacro), 15000)
    }
    request = null
    login = {}
    values = {}
    materials = {}
    uploadQueue = []
    remaining = null
    loginNetworkError = false
    if (document.title === title) document.title = previousTitle
    if (panel.dataset.officialView === viewer) panel.dataset.officialState = 'done'
  }

  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== popup ||
        event.data?.type !== 'official-popup-start' || event.data.viewer !== viewer ||
        panel.dataset.officialState !== 'ready') return
    panel.dataset.officialState = 'running'
    launchState = 'running'
    if (resetSession) {
      show('正在清理官网登录会话。')
      request = {action:'reset-login', input:{}, next:cleared=>{
        if (!cleared) {
          finish('官网登录会话未能清理。请在官网退出登录后重新启动。')
          return
        }
        sessionStorage.removeItem(resetKey)
        show('已清理官网登录会话，正在打开登录页。', loginUrl)
        navigate()
      }}
    } else {
      show('正在打开官网登录页。')
    }
  }, {signal})

  function openPortal() {
    if (signal.aborted || launchState !== 'awaiting-window') return
    popup = window.open('/official-session.html#' + viewer, '_blank', 'popup,width=1280,height=900')
    if (!popup) {
      show('Chrome 阻止了申报窗口。请允许弹出式窗口，再点击「打开申报窗口」。')
      return
    }
    panel.dataset.officialState = 'ready'
    launchState = 'ready'
    show('正在连接官网窗口。')
    waitForOperator()
    popupMonitor = setInterval(() => {
      if (popup.closed) finish('官网窗口已关闭。请刷新页面后重试。', 'approval-timeout')
    }, 750)
  }

  if (document.documentElement.hasAttribute('data-kantu')) {
    show('正在连接 Ui.Vision…')
    window.addEventListener('kantuInvokeSuccess', () => {
      if (panel.dataset.officialState === 'starting') show('请在当前工作台标签页确认 Ui.Vision 的启动提示。')
    }, {once:true, signal})
    deadline = setTimeout(() => {
      if (panel.dataset.officialState === 'starting') finish('Ui.Vision 未启动。若刚才取消了授权，请刷新页面后重试。', 'approval-timeout')
    }, 60000)
    window.dispatchEvent(new CustomEvent('kantuSaveAndRunMacro',{
      detail:{json:officialMacro(project,ticket,viewer,location.origin,resetSession),storageMode:'browser'}
    }))
  } else {
    finish('未检测到 Ui.Vision。请在已安装并启用扩展的 Chrome 中打开工作台。')
  }
  function reloadLogin() {
    if (signal.aborted || !loginNetworkError) return
    navigationRevision++
    loginNetworkError = false
    attemptedLogin = true
    waitingForLogin = true
    returnedHome = false
    entryAttempts = 0
    entryRetryAt = 0
    login = {}
    show('正在重新加载官网登录页。',loginUrl)
    waitForOperator()
    navigate()
  }

  return {dispose,reloadLogin,openPortal,focus:()=>popup?.focus()}
}
