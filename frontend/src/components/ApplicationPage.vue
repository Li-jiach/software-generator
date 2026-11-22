<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {Play} from 'lucide-vue-next'
import {api, statusName} from '../api'
import {markOfficialSessionReset, startOfficialViewer} from '../official-launch'
import {loginUrl} from '../official-macro'

const props=defineProps({project:Object})
const emit=defineEmits(['notify','navigate'])
const precheck=ref(null),loading=ref(false),running=ref(false)
const panel=ref(null),status=ref('等待启动申报。')
const loginRetry=ref(false),launchState=ref('')
const reloadWorkbench=()=>window.location.reload()
const destinations={form:'basic',manual:'source',source:'attachments',ownership:'attachments'}
const ready=computed(()=>precheck.value?.canStart&&!precheck.value.fieldIssues?.length&&precheck.value.checks.every(check=>check.status==='approved'))
let disposed=false,viewer

async function load(){
 loading.value=true
 try{precheck.value=await api(`/projects/${props.project.id}/application-precheck`)}
 catch(e){precheck.value=null;emit('notify',e.message,true)}
 finally{loading.value=false}
}
async function start(){
 if(!ready.value||running.value)return
 if(!document.documentElement.hasAttribute('data-kantu')){
  status.value='请在已安装并启用 Ui.Vision 的 Chrome 中启动申报。'
  return
 }
 const id=crypto.randomUUID()
 running.value=true
 status.value='正在检查审核状态…'
 try{
  const {ticket}=await api(`/projects/${props.project.id}/official-application/start`,{method:'POST'})
  if(disposed)return
  viewer?.dispose()
  viewer=startOfficialViewer({
   project:props.project.id,ticket,panel:panel.value,viewer:id,
   onStatus(text,canRetry,state){
    launchState.value=state
    status.value=text
    loginRetry.value=canRetry
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
 if(performance.getEntriesByType('navigation')[0]?.type==='reload' && location.hash==='#rpa')
  markOfficialSessionReset()
 load()
})
onUnmounted(()=>{
 disposed=true
 viewer?.dispose()
})
</script>

<template>
 <div class="page-header">
  <h1 class="page-title">官网自动申报</h1>
  <button class="btn btn-primary" :disabled="!ready||loading||running" @click="start"><Play :size="15"/> 启动申报</button>
 </div>
 <p class="alert">请在安装 Ui.Vision 的 Chrome 中启动。登录、安全验证和填写在独立官网窗口进行。审核通过的附件会生成申报 PDF，上传进度在下方显示。</p>
 <section class="panel application-panel">
  <div class="panel-header"><h2 class="panel-title">官网申报预检</h2><button class="btn btn-sm" :disabled="loading||running" @click="load">刷新审核状态</button></div>
  <div class="panel-body">
   <p v-for="issue in precheck?.fieldIssues" :key="issue.field" class="field-error">{{issue.message}}。<button class="btn btn-sm" @click="emit('navigate','basic')">去补填</button></p>
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
    <button v-if="loginRetry" class="btn btn-sm" type="button" @click="viewer?.reloadLogin()">重新加载官网登录页</button>
    <button v-if="launchState==='awaiting-window'" class="btn btn-primary btn-sm" type="button" @click="viewer?.openPortal()">打开申报窗口</button>
    <button v-if="['starting','approval-timeout'].includes(launchState)" class="btn btn-sm" type="button" @click="reloadWorkbench">刷新后重试</button>
    <button v-if="running&&['ready','running'].includes(launchState)" class="btn btn-sm" type="button" @click="viewer?.focus()">切换到申报窗口</button>
   </div>
  </div>
  <p class="live-message" role="status">{{status}}</p>
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

</style>
