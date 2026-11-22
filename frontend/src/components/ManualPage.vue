<script setup>
import {computed, onMounted, onUnmounted, ref, shallowRef, watch} from 'vue'
import {Camera, ChevronRight, Download, FileArchive, LoaderCircle, Play, RotateCcw, Square, Upload} from 'lucide-vue-next'
import {api, downloadFile, fileUrl, statusName} from '../api'
import {zipSync} from 'fflate'
import sourcePolicy from '../../../config/manual-source-policy.json'

const props=defineProps({project:Object,user:Object})
const emit=defineEmits(['refresh','notify'])
const job=ref(null), pending=ref(false), ready=ref(false)
const folderInput=ref(null), zipInput=ref(null), localSource=shallowRef(null), archiving=ref(false)
const uploadingZip=ref('')
const planning=ref(false)
const lastPlanJobId=ref(null)
const devtoolsGuide=ref(null)
const downloadDialog=ref(null), finalInput=ref(null), finalFile=ref(null)
const downloading=ref(false), uploadingFinal=ref(false), submitting=ref(false), downloaded=ref(false)
const manual=ref(null)
const logPane=ref(null)
const followLog=ref(true)
const url=ref(''), savedUrl=ref(''), loadingSettings=ref(true)
const testingSite=ref(false), testedUrl=ref(''), siteError=ref('')
const canTestSite=computed(()=>ready.value&&!!savedUrl.value&&url.value.trim()===savedUrl.value)
const sitePassed=computed(()=>canTestSite.value&&testedUrl.value===savedUrl.value)
watch([ready,url,savedUrl],()=>{testedUrl.value='';siteError.value=''},{flush:'sync'})
const sourceGroups={frontend:'前端',backend:'后端'}
const phases=['源码分析','功能目录','页面路径','主要操作','实景截图','Word 手册']
const stateNames={running:'进行中',source_ready:'源码分析完成',review:'准备截图',complete:'已完成',failed:'失败',cancelled:'已停止'}
const projectPath=computed(()=>`/projects/${encodeURIComponent(props.project.id)}`)
const path=computed(()=>`${projectPath.value}/manual-jobs`)
const active=computed(()=>job.value?.status==='running')
const canUploadFinal=computed(()=>downloaded.value||(manual.value?.status==='returned'&&manual.value?.attachmentId))
const runningStage=computed(()=>{
 if(archiving.value)return 0
 if(planning.value)return 1
 if(job.value?.status!=='running')return null
 return job.value.id===lastPlanJobId.value?Math.max(1,job.value.stage):job.value.stage
})
const running=computed(()=>runningStage.value!==null)
const result=computed(()=>job.value?.result||{})
const skippedCaptures=computed(()=>[...(result.value.unreachableShots||[]),...(result.value.failedShots||[])])
const canRetryCapture=computed(()=>job.value?.stage===4&&!!result.value.shots?.length&&
 ['running','failed','cancelled','review'].includes(job.value.status))
const modelLogs=computed(()=>job.value?.modelLogs||[])
const hasResults=computed(()=>result.value.sourceSelection||result.value.modules||result.value.pages||result.value.operations)
const sourceSelected=computed(()=>Boolean(localSource.value))
const canGenerate=computed(()=>!sourceSelected.value&&result.value.sourceSelection?.groups?.frontend.readPaths.length>0&&
 (job.value.status==='source_ready'||(job.value.status==='failed'&&job.value.stage>0&&!result.value.shots)))
const canContinue=computed(()=>canGenerate.value&&sitePassed.value)
const nextPlanJob=computed(()=>!pending.value&&canContinue.value&&job.value?.status==='source_ready'?job.value.id:null)
let timer, disposed=false, generation=0

watch(nextPlanJob,id=>{
 if(id&&id!==lastPlanJobId.value)generate()
})

function phaseDone(stage){
 return job.value&&(job.value.status==='complete'||job.value.stage>stage||
  (stage===0&&(job.value.status==='source_ready'||runningStage.value>0)))
}

function apply(next){
 if(disposed)return
 if(next?.id!==job.value?.id){
  followLog.value=true
  downloaded.value=Boolean(next?.id&&sessionStorage.getItem(downloadKey(next.id)))
 }
 job.value=next
 clearTimeout(timer)
 if(next?.status==='running')timer=setTimeout(poll,1000)
}
function downloadKey(id){
 return `manual-download:${props.user.id}:${props.project.id}:${id}`
}
async function confirmDownload(){
 if(downloading.value||job.value?.status!=='complete')return
 const id=job.value.id
 downloading.value=true
 try{
  await downloadFile(`${path.value}/${id}/word`,{method:'POST',body:{acknowledged:true}},'操作手册.docx')
  sessionStorage.setItem(downloadKey(id),'1')
  downloaded.value=true
  downloadDialog.value?.close()
 }catch(e){if(!disposed)emit('notify',e.message,true)}
 finally{downloading.value=false}
}
async function uploadFinal(event){
 const file=event.target.files[0]
 event.target.value=''
 if(!file||uploadingFinal.value||submitting.value)return
 if(!/\.(docx|pdf)$/i.test(file.name)){emit('notify','请选择 Word（.docx）或 PDF 文件。',true);return}
 const body=new FormData()
 body.append('file',file)
 body.append('category','操作手册')
 uploadingFinal.value=true
 try{
  const attachment=await api(`${projectPath.value}/files`,{method:'POST',body})
  finalFile.value={id:attachment.id,name:file.name}
  emit('refresh')
 }catch(e){if(!disposed)emit('notify',e.message,true)}
 finally{uploadingFinal.value=false}
}
async function submitFinal(){
 if(!finalFile.value||!manual.value||uploadingFinal.value||submitting.value)return
 submitting.value=true
 try{
  manual.value=await api(`${projectPath.value}/manual/submit`,{
   method:'POST',body:{attachmentId:finalFile.value.id,revision:manual.value.revision}
  })
  finalFile.value=null
  emit('refresh')
  emit('notify','操作手册已提交管理员审核。')
 }catch(e){
  if(e.status===409)manual.value=await api(`${projectPath.value}/manual`).catch(()=>manual.value)
  if(!disposed)emit('notify',e.message,true)
 }finally{submitting.value=false}
}
function trackLogScroll(event){
 const pane=event.currentTarget
 followLog.value=pane.scrollHeight-pane.scrollTop-pane.clientHeight<24
}
watch([modelLogs,logPane],()=>{
 if(followLog.value&&logPane.value)logPane.value.scrollTop=logPane.value.scrollHeight
},{flush:'post'})
async function poll(){
 const before=generation
 try{const next=await api(`${path.value}/${job.value.id}`);if(before===generation)apply(next)}
 catch(e){if(!disposed&&before===generation){emit('notify',e.message,true);if(!e.status||e.status>=500)timer=setTimeout(poll,5000)}}
}
async function command(action){
 if(pending.value)return
 pending.value=true
 generation++
 clearTimeout(timer)
 try{apply(await action())}
 catch(e){if(!disposed){emit('notify',e.message,true);apply(job.value)}}
 finally{pending.value=false}
}
async function saveUrl(){
 pending.value=true
 try{
  const settings=await api(`${path.value}/settings`,{method:'PUT',body:{url:url.value.trim()}})
  url.value=savedUrl.value=settings.url
  emit('notify',settings.url?'测试站点入口已保存':'测试站点入口已清除')
 }catch(e){emit('notify',e.message,true)}
 finally{pending.value=false}
}
async function folderArchive(files){
 const entries={}
 let bytes=0,count=0
 for(const file of files){
  const name=file.webkitRelativePath
  const parts=name.toLowerCase().split('/')
  const leaf=parts.at(-1)
  if(!name||name.length>350||parts.some(part=>!part||part.startsWith('.')||sourcePolicy.skip.includes(part)))continue
  if(!sourcePolicy.manifests.includes(leaf)&&!sourcePolicy.extensions.some(ext=>leaf.endsWith(ext)))continue
  if(!file.size||file.size>sourcePolicy.maxFileBytes)continue
  bytes+=file.size
  if(bytes>40_000_000||++count>10000)throw new Error('目录中的候选源码过多，请选择更小的项目范围。')
  entries[name]=new Uint8Array(await file.arrayBuffer())
 }
 if(!bytes)throw new Error('所选文件夹里没有可分析的前端或后端源码。')
 const name=Object.keys(entries)[0].split('/')[0].slice(0,100)
 return new File([zipSync(entries,{level:0})],`${name}.zip`,{type:'application/zip'})
}
async function uploadArchive(file, name){
 const data=new FormData()
 data.append('file',file)
 data.append('category','源程序')
 const uploaded=await api(`/projects/${encodeURIComponent(props.project.id)}/files`,{method:'POST',body:data})
 localSource.value={name,fileId:uploaded.id}
 emit('refresh')
 return uploaded.id
}
async function testSite(){
 if(!canTestSite.value||testingSite.value)return
 testingSite.value=true
 testedUrl.value=''
 siteError.value=''
 const entry=savedUrl.value
 try{
  await api(`${path.value}/preflight`,{method:'POST',body:{url:entry,browserReady:ready.value}})
  if(!disposed&&canTestSite.value&&savedUrl.value===entry)testedUrl.value=entry
 }catch(e){if(!disposed)siteError.value=e.message}
 finally{testingSite.value=false}
}
function startAnalysis(){
 if(!sourceSelected.value||!sitePassed.value||testingSite.value||active.value||loadingSettings.value)return
 return command(async()=>{
  const source=localSource.value
  archiving.value=Boolean(source.files)
  try{
   const attachmentId=source.fileId||await uploadArchive(await folderArchive(source.files),source.name)
   const next=await api(`${path.value}/source`,{method:'POST',body:{fileId:attachmentId,url:savedUrl.value,browserReady:ready.value}}).catch(error=>{
    if(error.status===422){testedUrl.value='';siteError.value=error.message}
    throw error
   })
   localSource.value=null
   return next
  }finally{archiving.value=false}
 })
}
function chooseFolder(event){
 const files=Array.from(event.target.files)
 event.target.value=''
 if(!files.length)return
 localSource.value={name:files[0].webkitRelativePath.split('/')[0],files}
}
async function chooseZip(event){
 const file=event.target.files[0]
 event.target.value=''
 if(!file||pending.value)return
 if(!/\.zip$/i.test(file.name)){
  emit('notify','请选择 ZIP 文件。',true)
  return
 }
 uploadingZip.value=file.name
 pending.value=true
 try{await uploadArchive(file,file.name)}
 catch(e){if(!disposed)emit('notify',e.message,true)}
 finally{uploadingZip.value='';pending.value=false}
}
async function generate(){
 if(!canContinue.value||pending.value)return
 lastPlanJobId.value=job.value.id
 planning.value=true
 try{
  await command(()=>api(`${path.value}/${job.value.id}/generate`,{
   method:'POST',body:{url:url.value.trim(),browserReady:ready.value}
  }))
 }finally{planning.value=false}
}
function reset(){
 return command(async()=>{
  if(job.value)await api(`${path.value}/reset`,{method:'POST'})
  if(job.value)sessionStorage.removeItem(downloadKey(job.value.id))
  localSource.value=null
  finalFile.value=null
  lastPlanJobId.value=null
  ready.value=false
  followLog.value=true
  emit('notify','生成状态已重置。')
  return null
 })
}
const clickPath=steps=>steps.map(s=>s.label).join(' → ')||'初始页面'
const moduleName=id=>result.value.modules?.find(m=>m.id===id)?.title||id
const depth=module=>{
 let current=module, level=0
 while(current?.parentId&&level<4){current=result.value.modules.find(m=>m.id===current.parentId);level++}
 return level
}
onMounted(async()=>{
 const results=await Promise.allSettled([api(path.value),api(`${path.value}/settings`),api(`${projectPath.value}/manual`)])
 if(disposed||generation)return
 const [latest, settings, review]=results
 if(latest.status==='fulfilled')apply(latest.value.job)
 if(settings.status==='fulfilled')url.value=savedUrl.value=settings.value.url
 if(review.status==='fulfilled')manual.value=review.value
 loadingSettings.value=false
 for(const response of results)if(response.status==='rejected')emit('notify',response.reason.message,true)
})
onUnmounted(()=>{disposed=true;clearTimeout(timer)})
</script>

<template>
  <section class="manual-section">
   <h2 class="panel-title">生成设置</h2>
   <fieldset :disabled="pending||active||loadingSettings||testingSite" class="manual-inputs">
    <div class="field full"><label for="manual-url">本机测试站点入口</label><input id="manual-url" v-model="url" type="url" placeholder="http://127.0.0.1:3000/" maxlength="500" :readonly="user.role!=='admin'"/><small v-if="user.role!=='admin'&&!savedUrl" class="muted">请联系管理员设置本项目的测试站点入口。</small></div>
    <div class="full actions">
     <label class="manual-verify"><input v-model="ready" type="checkbox" required/> 已在 Google Chrome 中打开测试站点，确认开发者工具可用，且无需登录即可访问</label>
     <button type="button" class="btn btn-sm" :disabled="!canTestSite" @click="testSite">{{testingSite?'正在测试站点…':'测试站点'}}</button>
     <button type="button" class="btn btn-sm" aria-haspopup="dialog" @click="devtoolsGuide.showModal()">查看开发者模式打开方式</button>
    </div>
    <p v-if="sitePassed" class="full muted" role="status">测试通过，可以开始分析。</p>
    <p v-if="siteError" class="full field-error" role="alert">{{siteError}}</p>
   </fieldset>
   <div class="actions" role="group" aria-label="手册生成操作">
    <input ref="folderInput" type="file" aria-label="选择路径" webkitdirectory multiple hidden @change="chooseFolder"/>
    <input ref="zipInput" type="file" accept=".zip,application/zip" hidden @change="chooseZip"/>
    <button v-if="user.role==='admin'" type="button" class="btn" :disabled="pending||active||loadingSettings||testingSite||url.trim()===savedUrl" @click="saveUrl">保存站点入口</button>
    <button type="button" class="btn" :disabled="pending||active||loadingSettings||testingSite" @click="folderInput.click()">选择路径</button>
    <button type="button" class="btn" :disabled="pending||active||loadingSettings||testingSite" @click="zipInput.click()"><FileArchive :size="14"/> 使用源码 ZIP</button>
    <button type="button" class="btn btn-primary" :disabled="pending||active||loadingSettings||testingSite||!sourceSelected||!sitePassed" @click="startAnalysis"><Play :size="15"/> 开始分析</button>
    <button v-if="active" type="button" class="btn" :disabled="pending" @click="command(()=>api(`${path}/${job.id}`,{method:'DELETE'}))"><Square :size="14"/> 停止任务</button>
    <button type="button" class="btn" :disabled="pending||loadingSettings||testingSite||!(job||sourceSelected||ready)" @click="reset"><RotateCcw :size="14"/> 重置状态</button>
    <button v-if="job?.status==='failed'&&canGenerate" type="button" class="btn btn-primary" :disabled="pending||!canContinue" @click="generate">重试当前步骤</button>
    <template v-if="result.shots">
     <button v-if="canRetryCapture" type="button" class="btn btn-primary" :disabled="pending" @click="command(()=>api(`${path}/${job.id}/capture`,{method:'POST'}))"><Camera :size="15"/> 重试当前步骤</button>
     <button v-if="job.status==='complete'" type="button" class="btn btn-primary" :disabled="downloading" @click="downloadDialog.showModal()"><Download :size="15"/> 下载 Word 手册</button>
    </template>
    <input ref="finalInput" type="file" accept=".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden @change="uploadFinal"/>
    <button v-if="canUploadFinal" type="button" class="btn" :disabled="uploadingFinal||submitting||manual?.status==='submitted'" @click="finalInput.click()"><Upload :size="15"/> {{uploadingFinal?'正在上传…':'上传并送审'}}</button>
    <button v-if="finalFile" type="button" class="btn btn-primary" :disabled="!manual||uploadingFinal||submitting||manual.status==='submitted'" @click="submitFinal">送审</button>
   </div>
   <p v-if="uploadingZip" class="muted" role="status">正在上传 {{uploadingZip}}</p>
   <p v-else-if="localSource" class="muted">{{localSource.fileId?'已上传':'已选择'}} {{localSource.name}}</p>
   <p v-if="finalFile" class="muted">已上传 {{finalFile.name}}，待送审</p>
   <p v-if="manual?.attachmentId" class="muted">最终手册 {{statusName(manual.status)}} · <a :href="fileUrl(project.id,manual.attachmentId)">{{manual.attachmentName}}</a></p>
   <p v-if="manual?.status==='returned'&&manual.comment" class="alert">{{manual.comment}}</p>
  </section>

  <dialog ref="downloadDialog" class="modal manual-guide" aria-labelledby="manual-download-title" @cancel.prevent="!downloading&&downloadDialog.close()">
   <div class="modal-head"><h3 id="manual-download-title">确认手册用途</h3></div>
   <div class="modal-body"><p>我已确认，AI 生成的内容不可用于软著申请，此次生成仅用作参考内容。</p></div>
   <div class="modal-foot">
    <button type="button" class="btn" :disabled="downloading" @click="downloadDialog.close()">取消</button>
    <button type="button" class="btn btn-primary" :disabled="downloading" @click="confirmDownload">{{downloading?'正在下载…':'确认下载'}}</button>
   </div>
  </dialog>
  <dialog ref="devtoolsGuide" class="modal manual-guide" aria-labelledby="manual-guide-title" @keydown.esc.prevent="devtoolsGuide.close()">
   <div class="modal-head">
    <h3 id="manual-guide-title">打开 Chrome 开发者工具</h3>
    <button type="button" class="btn btn-sm" autofocus @click="devtoolsGuide.close()">关闭</button>
   </div>
   <div class="modal-body">
    <ol>
     <li>在 Google Chrome 中打开本机测试站点，确认无需登录即可访问。</li>
     <li>点击 Chrome 右上角的「⋮」，选择「更多工具」→「开发者工具」。也可以使用快捷键。
      <ul>
       <li>Windows / Linux：<kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>I</kbd>，或 <kbd>F12</kbd></li>
       <li>macOS：<kbd>Command</kbd> + <kbd>Option</kbd> + <kbd>I</kbd></li>
      </ul>
     </li>
     <li>看到「元素」或「控制台」面板后，返回本页勾选确认。</li>
    </ol>
    <a href="https://developer.chrome.com/docs/devtools/open?hl=zh-cn" target="_blank" rel="noopener noreferrer">Chrome 官方教程 ↗</a>
   </div>
  </dialog>

  <section class="manual-section" aria-labelledby="manual-progress">
   <div class="manual-row">
    <h2 id="manual-progress" class="panel-title">解析进程</h2>
    <span v-if="running||job" class="badge" :class="!running&&job?.status==='complete'?'positive':!running&&job?.status==='failed'?'negative':'info'" role="status">
     <LoaderCircle v-if="running" class="manual-spinner" :size="14" aria-hidden="true"/>
     {{archiving?'正在读取源码':planning?'正在启动截图计划':stateNames[job.status]}}<template v-if="job&&!archiving"> · {{job.model}}</template>
    </span>
   </div>
   <ol class="manual-phases">
    <li v-for="(phase,i) in phases" :key="phase"
     :class="{current:runningStage===i||(job?.status==='review'&&job.stage===i),running:runningStage===i,done:phaseDone(i)&&runningStage!==i}"
     :aria-current="runningStage===i||(job?.status==='review'&&job.stage===i)?'step':undefined"><span>{{i}}</span>{{phase}}</li>
   </ol>
   <p v-if="job?.status==='source_ready'&&canGenerate&&!canContinue" class="alert" role="status">源码分析已完成。测试站点通过后，系统会自动开始规划截图。</p>
   <p v-else-if="job?.status==='source_ready'&&!sourceSelected&&!canGenerate" class="alert" role="status">源码分析已完成。自动截图需要可读取的前端源码。</p>
   <p v-if="archiving" class="muted" role="status">正在扫描并提交源码文件。</p>
   <p v-else-if="!job" class="muted">暂无解析任务</p>
   <ul v-else class="manual-events" aria-live="polite" aria-relevant="additions">
    <li v-for="(event,i) in job.events" :key="i"><span>{{event.title}}</span><p>{{event.text}}</p></li>
   </ul>
   <p v-if="job?.error" class="alert" role="alert">{{job.error}}</p>
  </section>

  <div v-if="job||archiving" class="manual-section manual-analysis">
  <details class="manual-analysis-panel manual-results">
   <summary class="panel-title">分析结果</summary>
   <p v-if="!hasResults" class="muted">{{running?'等待分析结果…':'暂无分析结果'}}</p>
   <details v-if="result.sourceSelection"><summary>已读取源码 · {{result.sourceSelection.paths.length}} / {{result.sourceSelection.candidates}} 个候选文件</summary><ul><li v-for="name in result.sourceSelection.paths" :key="name"><code>{{name}}</code></li></ul></details>
   <template v-if="result.sourceSelection?.groups">
    <details v-for="(label, side) in sourceGroups" :key="side">
     <summary>{{label}}分析 · 读取 {{result.sourceSelection.groups[side].readPaths.length}} / {{result.sourceSelection.groups[side].paths.length}} 个识别文件</summary>
     <p v-if="!result.sourceSelection.groups[side].paths.length" class="muted">未识别到{{label}}文件。</p>
     <p v-else-if="!result.sourceSelection.groups[side].readPaths.length" class="muted">没有可读取的 UTF-8 源码。</p>
     <div v-for="(facts, i) in result.sourceSelection.groups[side].facts" :key="i" class="manual-result"><p style="white-space:pre-wrap">{{facts}}</p></div>
     <details v-if="result.sourceSelection.groups[side].paths.length"><summary>{{label}}文件列表</summary><ul><li v-for="name in result.sourceSelection.groups[side].paths" :key="name" class="manual-result"><code>{{name}}</code></li></ul></details>
    </details>
   </template>
   <details v-if="result.modules"><summary>系统目标与目录 · {{result.modules.length}} 项</summary><p>{{result.overview}}</p><ol><li v-for="m in result.modules" :key="m.id" :style="{marginInlineStart:`${depth(m)*16}px`}">{{m.title}}</li></ol></details>
   <details v-if="result.pages"><summary>页面与点击路径 · {{result.pages.length}} 页</summary><div v-for="p in result.pages" :key="p.id" class="manual-result"><strong>{{moduleName(p.moduleId)}} / {{p.title}}</strong><p>{{p.description}}</p><p>{{clickPath(p.steps)}}</p><code>{{p.source}}</code></div></details>
   <details v-if="result.operations"><summary>主要按钮与窗口 · {{result.operations.length}} 项</summary><div v-for="o in result.operations" :key="o.id" class="manual-result"><strong>{{result.pages?.find(p=>p.id===o.pageId)?.title}} / {{o.title}}</strong><p>{{o.description}}</p><ol><li v-for="(instruction,i) in o.instructions" :key="i">{{instruction}}</li></ol></div></details>
  </details>
  <details class="manual-analysis-panel" @toggle="$event.target.open&&logPane&&followLog&&(logPane.scrollTop=logPane.scrollHeight)">
   <summary id="manual-log-title" class="panel-title">解析日志</summary>
   <p v-if="!modelLogs.length" class="muted">{{running?'等待模型回复…':'暂无模型回复'}}</p>
   <ol v-else ref="logPane" class="manual-log-entries" aria-labelledby="manual-log-title" tabindex="0" @scroll.passive="trackLogScroll">
    <li v-for="entry in modelLogs" :key="entry.id">
     <div class="manual-row">
      <strong>{{entry.task}}</strong>
      <span v-if="entry.receiving" class="muted">接收中…</span>
     </div>
     <pre v-if="entry.text">{{entry.text}}</pre>
     <p v-else class="muted">{{entry.receiving?'等待模型回复…':'未收到模型回复'}}</p>
     <small v-if="entry.truncated" class="muted">回复过长，仅显示开头。</small>
    </li>
   </ol>
  </details>
  </div>

  <section v-if="result.shots" class="manual-section manual-results">
   <div class="manual-row"><h2 class="panel-title">截图计划</h2><span class="muted">已核验 {{result.captured||0}} / {{result.shots.length}}<template v-if="skippedCaptures.length"> · 已跳过 {{skippedCaptures.length}}</template></span></div>
   <details :open="job.status==='review'"><summary>目标及操作顺序</summary><ul><li v-for="shot in result.shots" :key="shot.id" class="manual-result"><strong>{{shot.title}}</strong><p>{{clickPath(shot.steps)}} <ChevronRight :size="13"/> {{shot.visibleText}}</p></li></ul></details>
   <details v-if="result.skippedShots?.length" :open="job.status==='review'">
    <summary>未安排截图的操作 · {{result.skippedShots.length}} 项</summary>
    <ul><li v-for="shot in result.skippedShots" :key="shot.operationId" class="manual-result"><strong>{{shot.title}}</strong><p>{{shot.reason}}</p></li></ul>
   </details>
   <details v-if="skippedCaptures.length" open>
    <summary>Word 中待补的截图 · {{skippedCaptures.length}} 项</summary>
    <ul><li v-for="shot in skippedCaptures" :key="shot.id" class="manual-result"><strong>{{shot.title}}</strong><p>{{shot.reason}}</p></li></ul>
   </details>
  </section>
</template>
