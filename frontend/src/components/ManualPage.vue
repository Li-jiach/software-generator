<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {BookOpen, Camera, ChevronRight, Download, FileArchive, Play, Square} from 'lucide-vue-next'
import {api} from '../api'
import {zipSync} from 'fflate'
import sourcePolicy from '../../../config/manual-source-policy.json'

const props=defineProps({project:Object,editFirst:Boolean,user:Object})
const emit=defineEmits(['refresh','notify'])
const view=ref(props.editFirst?'edit':'generate'), job=ref(null), pending=ref(false), ready=ref(false)
const folder=ref([]), uploadKind=ref('folder')
const localFile=ref(null), fileId=ref(''), url=ref(''), savedUrl=ref(''), loadingSettings=ref(true)
const phases=['浏览器预检','功能目录','页面路径','主要操作','实景截图','Word 手册']
const stateNames={running:'进行中',review:'等待截图确认',complete:'已完成',failed:'失败',cancelled:'已停止'}
const path=computed(()=>`/projects/${encodeURIComponent(props.project.id)}/manual-jobs`)
const archives=computed(()=>props.project.files.filter(f=>/\.zip$/i.test(f.name)))
const hasUpload=computed(()=>uploadKind.value==='folder'?folder.value.length>0:!!localFile.value)
const active=computed(()=>['running','review'].includes(job.value?.status))
const result=computed(()=>job.value?.result||{})
let timer, disposed=false, generation=0

function apply(next){
 if(disposed)return
 job.value=next
 clearTimeout(timer)
 if(next?.status==='running')timer=setTimeout(poll,1800)
}
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
function start(){return command(async()=>{
 let selected=fileId.value
 if(hasUpload.value){
  const source=uploadKind.value==='folder'?await folderArchive(folder.value):localFile.value
  const data=new FormData()
  data.append('file',source);data.append('category','源程序')
  const uploaded=await api(`/projects/${encodeURIComponent(props.project.id)}/files`,{method:'POST',body:data})
  selected=uploaded.id
  fileId.value=selected
  localFile.value=null
  folder.value=[]
  uploadKind.value='existing'
  emit('refresh')
 }
 return api(path.value,{method:'POST',body:{fileId:selected,url:url.value.trim(),browserReady:ready.value}})
})}
const clickPath=steps=>steps.map(s=>s.label).join(' → ')||'初始页面'
const moduleName=id=>result.value.modules?.find(m=>m.id===id)?.title||id
const depth=module=>{
 let current=module, level=0
 while(current?.parentId&&level<4){current=result.value.modules.find(m=>m.id===current.parentId);level++}
 return level
}
onMounted(async()=>{
 const results=await Promise.allSettled([api(path.value),api(`${path.value}/settings`)])
 if(disposed||generation)return
 const [latest, settings]=results
 if(latest.status==='fulfilled')apply(latest.value.job)
 if(settings.status==='fulfilled')url.value=savedUrl.value=settings.value.url
 loadingSettings.value=false
 for(const response of results)if(response.status==='rejected')emit('notify',response.reason.message,true)
})
onUnmounted(()=>{disposed=true;clearTimeout(timer)})
</script>

<template>
 <div class="tabs" aria-label="手册工作区">
  <button :class="{active:view==='generate'}" @click="view='generate'"><BookOpen :size="15"/> 智能生成</button>
  <button :class="{active:view==='edit'}" @click="view='edit'">编辑与送审</button>
 </div>
 <iframe v-if="view==='edit'" class="workflow-frame manual-edit-frame" :src="`/workflow-preview.html?projectId=${encodeURIComponent(project.id)}#manual`" title="编辑操作手册" sandbox="allow-scripts allow-same-origin allow-downloads allow-modals"></iframe>
 <template v-else>
  <form class="manual-section" @submit.prevent="start">
   <h2 class="panel-title">生成设置</h2>
   <fieldset :disabled="pending||active||loadingSettings" class="manual-inputs">
    <div class="field"><label for="manual-source-kind">源码来源</label><select id="manual-source-kind" v-model="uploadKind"><option value="folder">本地项目文件夹</option><option value="zip">本地 ZIP</option><option value="existing">已上传的项目附件</option></select></div>
    <div v-if="uploadKind==='folder'" class="field"><label for="manual-folder">选择项目文件夹</label><input id="manual-folder" type="file" webkitdirectory multiple @change="folder=Array.from($event.target.files)"/></div>
    <div v-else-if="uploadKind==='zip'" class="field"><label for="manual-upload"><FileArchive :size="14"/> 上传源码 ZIP</label><input id="manual-upload" type="file" accept=".zip,application/zip" @change="localFile=$event.target.files[0]||null"/></div>
    <div v-else class="field"><label for="manual-archive">项目源码附件</label><select id="manual-archive" v-model="fileId"><option value="">选择已上传的 ZIP</option><option v-for="f in archives" :key="f.id" :value="f.id">{{f.name}} · v{{f.version}}</option></select></div>
    <div class="field full"><label for="manual-url">本机测试站点入口</label><input id="manual-url" v-model="url" type="url" placeholder="http://127.0.0.1:3000/" maxlength="500" :readonly="user.role!=='admin'"/><div v-if="user.role==='admin'" class="actions"><button type="button" class="btn" :disabled="url.trim()===savedUrl" @click="saveUrl">保存站点入口</button></div><small v-else-if="!savedUrl" class="muted">请联系管理员设置本项目的测试站点入口。</small></div>
    <label class="full manual-verify"><input v-model="ready" type="checkbox" required/> 已在默认浏览器打开测试站点，确认开发者工具可用，且无需登录即可访问</label>
   </fieldset>
   <div class="actions">
    <button class="btn btn-primary" :disabled="pending||active||!ready||!savedUrl||url.trim()!==savedUrl||!(uploadKind==='existing'?fileId:hasUpload)"><Play :size="15"/> 开始分析</button>
    <button v-if="active" type="button" class="btn" :disabled="pending" @click="command(()=>api(`${path}/${job.id}`,{method:'DELETE'}))"><Square :size="14"/> 停止任务</button>
   </div>
  </form>

  <section class="manual-section" aria-labelledby="manual-progress">
   <div class="manual-row"><h2 id="manual-progress" class="panel-title">解析进程</h2><span v-if="job" class="badge" :class="job.status==='complete'?'positive':job.status==='failed'?'negative':'info'">{{stateNames[job.status]}} · {{job.model}}</span></div>
   <ol class="manual-phases"><li v-for="(phase,i) in phases" :key="phase" :class="{current:job?.stage===i,done:job&&(job.stage>i||job.status==='complete')}" :aria-current="job?.stage===i?'step':undefined"><span>{{i}}</span>{{phase}}</li></ol>
   <p v-if="!job" class="muted">暂无解析任务</p>
   <ul v-else class="manual-events" aria-live="polite" aria-relevant="additions">
    <li v-for="(event,i) in job.events" :key="i"><span>{{event.title}}</span><p>{{event.text}}</p></li>
   </ul>
   <p v-if="job?.error" class="alert" role="alert">{{job.error}}</p>
  </section>

  <section v-if="result.sourceSelection||result.modules||result.pages||result.operations" class="manual-section manual-results">
   <h2 class="panel-title">分析结果</h2>
   <details v-if="result.sourceSelection"><summary>已读取源码 · {{result.sourceSelection.paths.length}} / {{result.sourceSelection.candidates}} 个候选文件</summary><ul><li v-for="name in result.sourceSelection.paths" :key="name"><code>{{name}}</code></li></ul></details>
   <details v-if="result.modules"><summary>系统目标与目录 · {{result.modules.length}} 项</summary><p>{{result.overview}}</p><ol><li v-for="m in result.modules" :key="m.id" :style="{marginInlineStart:`${depth(m)*16}px`}">{{m.title}}</li></ol></details>
   <details v-if="result.pages"><summary>页面与点击路径 · {{result.pages.length}} 页</summary><div v-for="p in result.pages" :key="p.id" class="manual-result"><strong>{{moduleName(p.moduleId)}} / {{p.title}}</strong><p>{{p.description}}</p><p>{{clickPath(p.steps)}}</p><code>{{p.source}}</code></div></details>
   <details v-if="result.operations"><summary>主要按钮与窗口 · {{result.operations.length}} 项</summary><div v-for="o in result.operations" :key="o.id" class="manual-result"><strong>{{result.pages?.find(p=>p.id===o.pageId)?.title}} / {{o.title}}</strong><p>{{o.description}}</p><ol><li v-for="(instruction,i) in o.instructions" :key="i">{{instruction}}</li></ol></div></details>
  </section>

  <section v-if="result.shots" class="manual-section manual-results">
   <div class="manual-row"><h2 class="panel-title">截图计划</h2><span class="muted">{{result.captured||0}} / {{result.shots.length}}</span></div>
   <details :open="job.status==='review'"><summary>目标及操作顺序</summary><ul><li v-for="shot in result.shots" :key="shot.id" class="manual-result"><strong>{{shot.title}}</strong><p>{{clickPath(shot.steps)}} <ChevronRight :size="13"/> {{shot.visibleText}}</p></li></ul></details>
   <div class="actions">
    <a v-if="job.status!=='running'||job.stage>=4" class="btn" :href="`/api${path}/${job.id}/plan`" download><Download :size="15"/> 下载截图计划</a>
    <button v-if="job.status==='review'" class="btn btn-primary" :disabled="pending" @click="command(()=>api(`${path}/${job.id}/capture`,{method:'POST'}))"><Camera :size="15"/> 确认计划并截图</button>
    <a v-if="job.status==='complete'" class="btn btn-primary" :href="`/api${path}/${job.id}/word`" download><Download :size="15"/> 下载 Word 手册</a>
   </div>
  </section>
 </template>
</template>
