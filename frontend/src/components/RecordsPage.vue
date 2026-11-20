<script setup>
import {computed, reactive, ref} from 'vue'
import {Plus, Receipt, Download, X} from 'lucide-vue-next'
import {api, fileUrl, stamp} from '../api'
const props=defineProps({project:Object,user:Object})
const emit=defineEmits(['refresh','notify'])
const open=ref(false),busy=ref(false),editingId=ref('')
const data=reactive({status:'待申报',referenceNo:'',occurredAt:'',note:'',evidenceId:''})
const status=computed(()=>props.project.records[0]?.status||'待申报')
function show(record=null){
 const now=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16)
 editingId.value=record?.id||''
 Object.assign(data,{status:record?.status||'待申报',referenceNo:record?.referenceNo||'',occurredAt:record?.occurredAt?.slice(0,19)||now,note:record?.note||'',evidenceId:record?.evidenceId||''})
 open.value=true
}
async function save(){
 if(busy.value)return
 busy.value=true
 try{
  const saved=await api(`/projects/${props.project.id}/records${editingId.value?'/'+editingId.value:''}`,{method:editingId.value?'PUT':'POST',body:data})
  open.value=false;emit('refresh',saved);emit('notify','申报记录已保存')
 }catch(e){emit('notify',e.message,true)}finally{busy.value=false}
}
async function remove(record){
 if(busy.value||!window.confirm('删除这条申报记录？'))return
 busy.value=true
 try{
  const saved=await api(`/projects/${props.project.id}/records/${record.id}`,{method:'DELETE'})
  emit('refresh',saved);emit('notify','记录已删除')
 }catch(e){emit('notify',e.message,true)}finally{busy.value=false}
}
function exportRecords(){const content=['软件项目：'+props.project.name+' '+props.project.version,...props.project.records.map(r=>`${stamp(r.occurredAt)}\t${r.status}\t${r.referenceNo||''}\n${r.note}\n登记人：${r.actor}`)].join('\n\n');const url=URL.createObjectURL(new Blob([content],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=props.project.id+'_申报记录.txt';a.click();URL.revokeObjectURL(url)}
</script>
<template>
 <div class="page-header"><h1 class="page-title sr-only">申报记录</h1><div class="actions"><button class="btn" :disabled="!project.records.length" @click="exportRecords"><Download :size="15"/>导出记录</button><button v-if="['admin','adminDept'].includes(user.role)" class="btn btn-primary" @click="show()"><Plus :size="15"/>登记办理记录</button></div></div>
 <div class="panel project-head"><div class="main-name"><span class="row-avatar"><Receipt :size="20"/></span><div><h3>{{status}}</h3><p>{{project.records[0]?.referenceNo||'尚无受理或登记编号'}}</p></div></div><span class="badge info">{{project.records.length}} 条记录</span></div>
 <section class="panel"><div class="panel-header"><h3 class="panel-title">办理时间线</h3></div><div class="panel-body"><div v-for="r in project.records" :key="r.id" class="timeline-item"><span class="timeline-point"><Receipt :size="13"/></span><div class="timeline-content"><div class="record-row-heading"><strong>{{r.status}}</strong><div v-if="['admin','adminDept'].includes(user.role)" class="actions"><button class="btn btn-sm" @click="show(r)">编辑</button><button class="btn btn-sm" @click="remove(r)">删除</button></div></div><p>{{r.note}}</p><p v-if="r.referenceNo">受理 / 登记编号：{{r.referenceNo}}</p><a v-if="r.evidenceId" :href="fileUrl(project.id,r.evidenceId)" class="cite-chip"><Download :size="12"/>查看凭证原件</a><div><small>{{stamp(r.occurredAt)}} · {{r.actor}}</small></div></div></div><div v-if="!project.records.length" class="empty"><Receipt :size="32"/><strong>暂无申报记录</strong></div></div></section>
 <div v-if="open" class="overlay" @click.self="!busy&&(open=false)">
  <form class="modal" @submit.prevent="save">
   <div class="modal-head"><h3>{{editingId?'编辑办理记录':'登记办理记录'}}</h3><button type="button" class="btn icon-btn" aria-label="关闭" :disabled="busy" @click="open=false"><X :size="17"/></button></div>
   <div class="modal-body form-fields">
    <div class="field"><label for="record-status">办理状态</label><select id="record-status" v-model="data.status"><option v-for="s in ['待申报','已提交','已受理','待补正','审核中','登记完成','已撤回','未通过']" :key="s">{{s}}</option></select></div>
    <div class="field"><label for="record-time">办理时间</label><input id="record-time" v-model="data.occurredAt" type="datetime-local" step="1" required/></div>
    <div class="field full"><label for="record-reference">真实受理号 / 登记号</label><input id="record-reference" v-model="data.referenceNo" :required="['已受理','登记完成'].includes(data.status)" maxlength="100"/></div>
    <div class="field full"><label for="record-note">办理说明</label><textarea id="record-note" v-model="data.note" rows="4" required maxlength="5000"></textarea></div>
    <div class="field full"><label for="record-evidence">关联凭证</label><select id="record-evidence" v-model="data.evidenceId"><option value="">暂不关联</option><option v-for="f in project.files" :key="f.id" :value="f.id">{{f.name}} · v{{f.version}}</option></select></div>
   </div>
   <div class="modal-foot"><button class="btn btn-primary" :disabled="busy">{{busy?'保存中…':'保存记录'}}</button></div>
  </form>
 </div>
</template>
