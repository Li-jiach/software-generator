import {fieldMap, loginUrl, officialMacro, portalOrigin, registrationUrl, stages} from './official-macro.js'

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
  let login = {}
  let values = {}
  let openedEntry = false
  let returnedHome = false
  let attemptedLogin = false
  let currentStage
  let expectedStage = 'application'
  let remaining
  let attempts

  function show(text, url) {
    if (url) frame.src = url
    onStatus(text)
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
    request = {action:'navigate', input:{openedEntry}, next:onNavigation}
  }

  function onNavigation(state) {
    if (state === 'opened') openedEntry = true
    if (state === 'login-required' && !attemptedLogin) show('正在打开官网登录页。', loginUrl)
    if (state === 'home' && !returnedHome) {
      returnedHome = true
      show('正在返回软件登记列表。', registrationUrl)
    }
    if (state === 'login' && !attemptedLogin) {
      attemptedLogin = true
      openedEntry = false
      returnedHome = false
      show('若官网要求登录或安全验证，请直接在下方操作。')
      if (login.username) loginStep('organization')
      waitForOperator()
      return
    }
    if (state === expectedStage) {
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
      if (!result || result.conflict) {
        finish(result?.conflict ? '官网表单已有不同的软件名称或版本，请先核对。' : '官网页面已切换，请回工作台重新启动。')
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
    request = null
    const timer = setTimeout(() => {
      port.close()
      if (signal.aborted || panel.dataset.officialState !== 'running') return
      if (step.action === 'login' && step.input.stage === 'submit') navigate()
      else request = step
    }, 1500)
    port.onmessage = ({data}) => {
      clearTimeout(timer)
      port.close()
      if (signal.aborted || panel.dataset.officialState !== 'running') return
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
      show('正在打开官网软件登记。',registrationUrl)
      panel.dataset.officialState = 'running'
      waitForOperator()
    } catch (error) {
      if (!signal.aborted) finish(error.message)
    }
  }, {signal})

  function dispose() {
    controller.abort()
    clearTimeout(deadline)
    request = null
    login = {}
    values = {}
    remaining = null
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
  return dispose
}
