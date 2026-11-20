<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {Check, Circle, LoaderCircle, Play} from 'lucide-vue-next'
import {api, stamp, statusName} from '../api'

const props=defineProps({project:Object})
const emit=defineEmits(['notify','navigate'])
const precheck=ref(null),loading=ref(false),activeStep=ref(-1),events=ref([])
const steps=[
 {name:'申报材料预检',detail:'检查当前版本的填报、手册、源程序鉴别材料和权属证明。'},
 {name:'准备填写及上传',detail:'预览使用通过审核的表单和附件。'},
 {name:'官网验证与最终确认',detail:'接入官网后由授权人员完成。'},
 {name:'回执存档',detail:'等待官网实际返回回执。'}
]
const destinations={form:'basic',manual:'source',source:'attachments',ownership:'attachments'}
const ready=computed(()=>precheck.value?.canStart&&precheck.value.checks.every(check=>check.status==='approved'))
let timer,disposed=false

async function load(){
 loading.value=true
 try{precheck.value=await api(`/projects/${props.project.id}/application-precheck`)}
 catch(e){precheck.value=null;emit('notify',e.message,true)}
 finally{loading.value=false}
}
function finish(index,text){
 events.value[index]={text,time:new Date()}
}
async function start(){
 if(!ready.value||activeStep.value>=0)return
 events.value=[]
 activeStep.value=0
 try{
  await api(`/projects/${props.project.id}/application-preview/start`,{method:'POST'})
  if(disposed)return
  finish(0,'服务端确认四项材料均已审核通过')
  activeStep.value=1
  timer=setTimeout(()=>{
   finish(1,'填写及上传流程预览完成，等待接入官网')
   activeStep.value=-1
  },1000)
 }catch(e){
  if(disposed)return
  activeStep.value=-1
  emit('notify',e.message,true)
  await load()
 }
}
onMounted(load)
onUnmounted(()=>{disposed=true;clearTimeout(timer)})
</script>

<template>
 <div class="page-header">
  <h1 class="page-title">官网自动申报</h1>
  <button class="btn btn-primary" :disabled="!ready||loading||activeStep>=0" @click="start"><Play :size="15"/> 启动申报预览</button>
 </div>
 <p class="alert">当前为流程预览，官网验证、材料提交和回执存档将在接入官网后执行。</p>
 <section class="panel application-panel">
  <div class="panel-header"><h2 class="panel-title">官网申报预检</h2><button class="btn btn-sm" :disabled="loading||activeStep>=0" @click="load">刷新审核状态</button></div>
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
 <section class="panel application-panel">
  <div class="panel-header"><h2 class="panel-title">申报流程与执行记录</h2></div>
  <div class="panel-body" aria-live="polite">
   <div v-for="(step,index) in steps" :key="step.name" class="timeline-item">
    <span class="timeline-point" :class="{good:events[index], 'step-running':activeStep===index}">
     <Check v-if="events[index]" :size="14" aria-label="已完成"/>
     <LoaderCircle v-else-if="activeStep===index" :size="15" class="step-spinner" aria-label="执行中"/>
     <Circle v-else :size="10" aria-label="等待执行"/>
    </span>
    <div class="timeline-content">
     <strong>{{step.name}}</strong>
     <p>{{step.detail}}</p>
     <small v-if="events[index]">{{stamp(events[index].time)}} · {{events[index].text}}</small>
     <small v-else-if="activeStep===index">执行中…</small>
    </div>
   </div>
  </div>
 </section>
</template>
