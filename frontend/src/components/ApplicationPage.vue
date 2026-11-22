<script setup>
import {computed, nextTick, onMounted, onUnmounted, ref} from 'vue'
import {Play} from 'lucide-vue-next'
import {api, statusName} from '../api'
import {startOfficialViewer} from '../official-launch'
import {loginUrl} from '../official-macro'

const props=defineProps({project:Object})
const emit=defineEmits(['notify','navigate'])
const precheck=ref(null),loading=ref(false),running=ref(false)
const panel=ref(null),frame=ref(null),frameVisible=ref(false),status=ref('等待启动申报。')
const loginRetry=ref(false)
const viewport=ref(null),frameStyle=ref({}),fullscreen=ref(false)
const destinations={form:'basic',manual:'source',source:'attachments',ownership:'attachments'}
const ready=computed(()=>precheck.value?.canStart&&precheck.value.checks.every(check=>check.status==='approved'))
let disposed=false,viewer,resize

function updateFrameSize(){
 const {clientWidth:width,clientHeight:height}=viewport.value
 if(!width||!height)return
 const layoutWidth=Math.max(width,1280)
 const scale=width/layoutWidth
 frameStyle.value={width:layoutWidth+'px',height:height/scale+'px',zoom:scale}
}
function updateFullscreen(){fullscreen.value=document.fullscreenElement===panel.value}
async function toggleFullscreen(){
 try{
  if(fullscreen.value)await document.exitFullscreen()
  else await panel.value.requestFullscreen()
 }catch{emit('notify','当前浏览器无法切换全屏',true)}
}

async function load(){
 loading.value=true
 try{precheck.value=await api(`/projects/${props.project.id}/application-precheck`)}
 catch(e){precheck.value=null;emit('notify',e.message,true)}
 finally{loading.value=false}
}
async function start(){
 if(!ready.value||running.value)return
 running.value=true
 status.value='正在检查审核状态…'
 try{
  const {ticket}=await api(`/projects/${props.project.id}/official-application/start`,{method:'POST'})
  if(disposed)return
  viewer?.dispose()
  frameVisible.value=false
  frame.value.removeAttribute('src')
  viewer=startOfficialViewer({
   project:props.project.id,ticket,panel:panel.value,frame:frame.value,
   onStatus(text,canRetry){
    status.value=text
    loginRetry.value=canRetry
    if(!frameVisible.value&&frame.value.hasAttribute('src')){
     frameVisible.value=true
     nextTick(()=>panel.value?.scrollIntoView({block:'start'}))
    }
   },
   onFinish(){running.value=false}
  })
  panel.value.scrollIntoView({block:'start'})
 }catch(e){
  if(disposed)return
  status.value=e.message
  running.value=false
  emit('notify',e.message,true)
  await load()
 }
}
onMounted(()=>{
 resize=new ResizeObserver(updateFrameSize)
 resize.observe(viewport.value)
 document.addEventListener('fullscreenchange',updateFullscreen)
 load()
})
onUnmounted(()=>{
 disposed=true
 viewer?.dispose()
 resize?.disconnect()
 document.removeEventListener('fullscreenchange',updateFullscreen)
})
</script>

<template>
 <div class="page-header">
  <h1 class="page-title">官网自动申报</h1>
  <button class="btn btn-primary" :disabled="!ready||loading||running" @click="start"><Play :size="15"/> 启动申报</button>
 </div>
 <p class="alert">请在安装 Ui.Vision 的 Chrome 中启动。可在实时申报页面查看填写进度，并直接操作官网安全验证。</p>
 <section class="panel application-panel">
  <div class="panel-header"><h2 class="panel-title">官网申报预检</h2><button class="btn btn-sm" :disabled="loading||running" @click="load">刷新审核状态</button></div>
  <div class="panel-body">
   <p v-if="loading&&!precheck" class="muted">正在读取审核状态…</p>
   <div v-for="check in precheck?.checks" :key="check.kind" class="application-check">
    <div><strong>{{check.label}}</strong><p v-if="check.comment&&check.status==='returned'" class="field-error">{{check.comment}}</p></div>
    <div class="actions">
     <span class="badge" :class="check.status==='approved'?'positive':'warning'">{{({draft:'待送审',stale:'附件已变更，待重新送审'})[check.status]||statusName(check.status)}}</span>
     <button class="btn btn-sm" @click="emit('navigate',destinations[check.kind])">查看材料</button>
    </div>
   </div>
  </div>
 </section>
 <section id="official-live" ref="panel" class="panel application-panel live-status">
  <div class="panel-header">
   <h2 class="panel-title">实时申报状态</h2>
   <div class="actions">
    <a class="btn btn-sm" :href="loginUrl" target="_blank" rel="noopener noreferrer">在新标签页打开官网</a>
    <button v-if="frameVisible&&loginRetry" class="btn btn-sm" type="button" @click="viewer?.reloadLogin()">重新加载官网登录页</button>
    <button v-if="frameVisible" class="btn btn-sm" type="button" @click="toggleFullscreen">{{fullscreen?'退出全屏':'全屏查看'}}</button>
   </div>
  </div>
  <p class="live-message" role="status">{{status}}</p>
  <div v-show="frameVisible" ref="viewport" class="official-viewport">
   <iframe id="official-browser" ref="frame" class="official-browser" :style="frameStyle" title="中国版权保护中心实时申报页面"></iframe>
  </div>
 </section>
</template>

<style scoped>
.live-status {
  min-width: 0;
  scroll-margin-top: 80px;
  overflow: hidden;
}

.live-message {
  margin: 0;
  padding: 14px 20px;
}

.official-viewport {
  height: max(340px, calc(100dvh - 210px));
  overflow: hidden;
  border-top: 1px solid #e3e7f1;
}

.official-browser {
  display: block;
  border: 0;
  background: white;
}

.live-status:fullscreen {
  display: flex;
  flex-direction: column;
}

.live-status:fullscreen .official-viewport {
  flex: 1;
  min-height: 0;
}
</style>
