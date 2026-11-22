import {fieldMap, loginUrl, officialMacro, portalOrigin, stages} from './official-macro.js'

export function startOfficialViewer({project, ticket, panel, frame, onStatus, onFinish}) {
  const viewer = crypto.randomUUID()
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
  let entryAttempts = 0
  let entryRetryAt = 0
  let returnedHome = false
  let attemptedLogin = false
  let resumedRegistration = false
  let waitingForLogin = false
  let loginNetworkError = false
  let frameRevision = 0
  let currentStage
  let expectedStage = 'application'
  let remaining
  let attempts

  function show(text, url) {
    if (url) frame.src = url
    onStatus(text, loginNetworkError)
  }

  function finish(text) {
    dispose()
    show(text)
    onFinish()
  }

  function waitForOperator() {
    clearTimeout(deadline)
    deadline = setTimeout(() => finish('等待官网超时，可继续操作下方页面，或回工作台重新启动。'), 300000)
  }

  function navigate() {
    const waitForEntry = entryAttempts >= 2 || Date.now() < entryRetryAt
    request = {action:'navigate', input:{waitForEntry,observingLogin:waitingForLogin}, next:onNavigation}
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
      show('官网仍停在软件登记列表。请处理下方官网提示，或手动点击 R11「立即登记」，宏会等待申请页。')
    if (state === 'registration-session-missing' || (resumedRegistration && ['login', 'inline-login'].includes(state))) {
      finish(state === 'registration-session-missing'
        ? '官网未读取到登录会话，自动填报已暂停。请在独立官网标签页登录后继续 R11 登记。'
        : '官网在进入 R11 时再次要求登录，自动填报已暂停。请在独立官网标签页登录后继续 R11 登记。')
      return
    }
    if (state === 'registration-unavailable')
      show('正在等待官网启用 R11「立即登记」。若按钮持续灰色，可在新标签页打开官网继续。')
    if (state === 'registration-dialog')
      show('官网弹出了登记提示。请在下方查看并处理，宏会等待进入申请页。')
    if (state === 'form-loading') show('已进入 R11，正在等待申请表加载。')
    if (state === 'home' && !returnedHome) {
      returnedHome = true
      resumedRegistration = attemptedLogin
      show('正在从官网用户中心进入软件登记。')
      request = {action:'registration-list', input:{}, next:navigate}
      return
    }
    if (state === 'home' && resumedRegistration) {
      show('已进入官网用户中心。请在下方选择「版权登记 → 软件登记」，宏会继续。')
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
        show('官网正在等待登录或安全验证，请在下方继续操作。')
        navigate()
        return
      }
      attemptedLogin = true
      returnedHome = false
      show('若官网要求登录或安全验证，请直接在下方操作。')
      if (login.username) loginStep('organization')
      else navigate()
      return
    }
    if (state === expectedStage) {
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
      finish('官网已进入确认页，请核对下方申请。')
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
    if (currentStage === 'features') {
      finish(missing.length ? '请在下方核对未填写的项目：' + missing.join('、') :
        '已填写工作台提供的基础信息。请在下方核对官网字段及技术特点标签。')
      return
    }

    expectedStage = currentStage === 'application' ? 'development' : 'features'
    waitForOperator()
    if (missing.length) {
      show('请在下方核对以下项目，并点击下一步：' + missing.join('、'))
      navigate()
      return
    }
    request = {action:'advance',input:{stage:currentStage},next:()=>{
      show('正在进入下一页。若有官网提示，请在下方处理后继续。')
      navigate()
    }}
  }

  window.addEventListener('message', event => {
    if (event.origin !== portalOrigin || event.source !== frame.contentWindow ||
        event.data?.type !== 'official-frame-step' || event.data.viewer !== viewer || !event.ports[0]) return
    const port = event.ports[0]
    if (!request) {port.close();return}
    const step = request
    const revision = frameRevision
    request = null
    const timer = setTimeout(() => {
      port.close()
      if (signal.aborted || revision !== frameRevision || panel.dataset.officialState !== 'running') return
      if (step.action === 'login' && step.input.stage === 'submit') navigate()
      else request = step
    }, 1500)
    port.onmessage = ({data}) => {
      clearTimeout(timer)
      port.close()
      if (signal.aborted || revision !== frameRevision || panel.dataset.officialState !== 'running') return
      if (data.error) finish('Ui.Vision 无法操作当前官网控件，请在下方人工核对。')
      else step.next(data.result)
    }
    port.postMessage({action:step.action,input:step.input})
  }, {signal})

  window.addEventListener('copyrightStartOfficial', async event => {
    const launch = event.detail
    if (!viewer || launch?.viewer !== viewer || panel.dataset.officialState !== 'starting') return
    panel.dataset.officialState = 'loading'
    show('正在检查当前审核版本。')
    try {
      const path = '/api/projects/' + encodeURIComponent(launch.project) + '/official-application/consume'
      const response = await fetch(path,{
        method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:launch.ticket}),
        cache:'no-store', signal
      })
      if (!response.ok) throw new Error('启动凭证已失效，或审核状态已变化。请回工作台重新启动。')
      const {form,login:account} = await response.json()
      if (signal.aborted) return
      login = account
      values = Object.fromEntries(Object.keys(fieldMap).filter(key=>form[key]).map(key=>[key,form[key]]))
      const hardware = (cpu,ram,disk) => [cpu&&'CPU '+cpu,ram&&'内存 '+ram,disk&&'硬盘 '+disk].filter(Boolean).join('，')
      values.developmentHardware = hardware(form.devCPU,form.devRAM,form.devDisk)
      values.runtimeHardware = hardware(form.runCPU,form.runRAM,form.runDisk)
      if (values.descriptionType === '修改（含翻译、合成）') values.descriptionType = '修改（含翻译软件、合成软件）'
      navigate()
      show('正在打开官网登录页。',loginUrl)
      panel.dataset.officialState = 'running'
      waitForOperator()
    } catch (error) {
      if (!signal.aborted) finish(error.message)
    }
  }, {signal})

  function dispose() {
    controller.abort()
    clearTimeout(deadline)
    clearTimeout(loginDelay)
    request = null
    login = {}
    values = {}
    remaining = null
    loginNetworkError = false
    if (document.title === title) document.title = previousTitle
    if (panel.dataset.officialView === viewer) panel.dataset.officialState = 'done'
  }

  if (document.documentElement.hasAttribute('data-kantu')) {
    show('正在连接 Ui.Vision…')
    window.addEventListener('kantuInvokeSuccess', () => {
      if (panel.dataset.officialState === 'starting') show('请按 Ui.Vision 提示确认。官网加载后可直接在下方操作。')
    }, {once:true, signal})
    deadline = setTimeout(() => {
      if (panel.dataset.officialState === 'starting') finish('Ui.Vision 未启动。请确认已允许网页启动宏，再点击「启动申报」。')
    }, 60000)
    window.dispatchEvent(new CustomEvent('kantuSaveAndRunMacro',{
      detail:{json:officialMacro(project,ticket,viewer,location.origin),storageMode:'browser'}
    }))
  } else {
    finish('未检测到 Ui.Vision。请在已安装并启用扩展的 Chrome 中打开工作台。')
  }
  function reloadLogin() {
    if (signal.aborted || !loginNetworkError) return
    frameRevision++
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

  return {dispose,reloadLogin}
}
