<script setup>
import {computed, nextTick, reactive, ref, watch} from 'vue'
import {Save, Send, ShieldCheck, Check, RotateCcw, Copy, FileCheck2} from 'lucide-vue-next'
import {FIELDS, GROUPS} from '../fields'
import {api, stamp} from '../api'
const props = defineProps({project:Object,user:Object,projects:Array,reviewOnly:Boolean})
const emit=defineEmits(['refresh','notify','dirty'])
const revision=ref(props.project.revision)
const form=reactive({}),tab=ref(props.reviewOnly?'reviews':'form'),busy=ref(false),validation=ref([]),sourceId=ref(''),suggested=ref({}),selected=ref([])
const required=FIELDS.filter(f=>f.required),filled=computed(()=>required.filter(f=>String(form[f.id]??'').trim()).length)
function loadForm(p){
  Object.keys(form).forEach(k=>delete form[k]);Object.assign(form,p.form)
  revision.value=p.revision;validation.value=p.validation||[];emit('dirty',false)
}
watch(()=>props.project,loadForm,{immediate:true})
function editable(f){return props.project.formStatus!=='submitted'&&(props.user.role==='admin'||props.user.role===f.dept)}
function dirty(){emit('dirty',JSON.stringify(form)!==JSON.stringify(props.project.form))}
async function run(fn){busy.value=true;try{await fn()}catch(e){emit('notify',e.message,true)}finally{busy.value=false}}
async function save(){
  const fields=Object.fromEntries(FIELDS.filter(editable).filter(f=>Object.hasOwn(form,f.id)).map(f=>[f.id,form[f.id]]))
  const saved=await api(`/projects/${props.project.id}/form`,{method:'PUT',body:{fields,revision:revision.value}})
  loadForm(saved)
  emit('refresh',saved)
  return saved
}
async function saveDraft(){await run(async()=>{await save();emit('notify','草稿已保存')})}
async function submit(){await run(async()=>{
  const saved=await save()
  if(saved.validation.length){emit('notify',`草稿已保存，还有 ${saved.validation.length} 项需要完善。修改后可再次提交。`,true);return}
  const submitted=await api(`/projects/${saved.id}/form/submit`,{method:'POST',body:{revision:saved.revision}})
  emit('refresh',submitted);emit('notify','已提交管理员核实')
})}
async function validate(){const {validation:errors}=await save();emit('notify',errors.length?`还有 ${errors.length} 项需要完善`:'填报校验通过',errors.length>0)}
async function review(field,status){let comment='';if(status==='returned'){comment=window.prompt('请填写退回原因');if(!comment?.trim())return}await run(async()=>{await api(`/projects/${props.project.id}/form/review`,{method:'POST',body:{field,status,comment}});emit('refresh');emit('notify',status==='approved'?'审核已通过':'已退回修改')})}
async function loadReuse(){if(!sourceId.value)return;await run(async()=>{const r=await api(`/projects/${props.project.id}/reuse/${sourceId.value}`);suggested.value=r.fields;selected.value=[]})}
function applyReuse(){for(const key of selected.value){const f=FIELDS.find(f=>f.id===key);if(f&&editable(f))form[key]=suggested.value[key]}dirty();tab.value='form';emit('notify','已填入所选历史字段，请核对并保存')}
const reuseFields=computed(()=>FIELDS.filter(f=>!['fullName','version','devFinish','copyrightOwner'].includes(f.id)&&editable(f)&&suggested.value[f.id]))
async function showAssistantField(id){
  tab.value='form'
  await nextTick()
  document.getElementById('field-'+id)?.scrollIntoView({block:'center'})
}
defineExpose({showAssistantField})
function errors(id){return validation.value.filter(v=>v.field===id)}
</script>
<template>
  <h1 v-if="!reviewOnly" class="page-title sr-only">基础信息填报</h1>
  <div v-if="!reviewOnly" class="panel summary-bar"><div><strong>{{filled}} / {{required.length}}</strong><span class="muted sm"> 必填项已填写</span></div><div class="progress-track"><b :style="{width:filled/required.length*100+'%'}"></b></div><span class="badge" :class="project.formStatus==='approved'?'positive':'info'">v{{project.formVersion}}</span></div>
  <div v-if="!reviewOnly" class="tabs"><button v-for="t in [['form','填写信息'],['reuse','历史复用']]" :key="t[0]" :class="{active:tab===t[0]}" @click="tab=t[0]">{{t[1]}}</button></div>
  <template v-if="tab==='form'"><div v-if="project.formStatus==='submitted'" class="alert">表单已提交核实，审核期间暂停修改。</div><div class="basic-groups"><section v-for="(name,group) in GROUPS" :key="group" class="panel basic-group"><div class="panel-header"><h3 class="panel-title">{{name}}</h3><span class="badge info">{{group==='basic'?'行政业务办':'研发中心'}}</span></div><div class="panel-body"><div class="form-fields"><div v-for="f in FIELDS.filter(f=>f.group===group)" :key="f.id" class="field" :class="{full:f.type==='textarea'}"><label class="field-label" :for="'field-'+f.id">{{f.label}} <span v-if="f.required" class="required">*</span> <span v-if="project.assistantReferenceFields?.includes(f.id)" class="badge warning" title="请核对实际资料并人工修订，切勿直接用于申报">AI 仅供参考</span></label><select v-if="f.type==='select'" :id="'field-'+f.id" v-model="form[f.id]" :disabled="!editable(f)||busy" @change="dirty"><option value="">请选择</option><option v-for="o in f.opts" :key="o">{{o}}</option></select><textarea v-else-if="f.type==='textarea'" :id="'field-'+f.id" v-model="form[f.id]" :disabled="!editable(f)||busy" :rows="f.id==='mainFunction'?8:4" @input="dirty"></textarea><input v-else :id="'field-'+f.id" v-model="form[f.id]" :type="f.type==='number'?'number':f.type==='date'?'date':'text'" :min="f.type==='number'?0:undefined" :disabled="!editable(f)||busy" @input="dirty"/><span v-if="f.id==='mainFunction'" class="muted tiny">{{String(form.mainFunction||'').replace(/\s/g,'').length}} / 500—1300 字</span><span v-for="e in errors(f.id)" :key="e.message" class="field-error">{{e.message}}</span><div v-if="project.formReviews[f.id]?.status==='returned'" class="field-error">退回意见：{{project.formReviews[f.id].comment}}</div></div></div></div></section></div></template>
  <section v-if="tab==='reviews'" class="panel"><div class="panel-header"><h3 class="panel-title">字段核验</h3><button v-if="user.role==='admin'" class="btn btn-soft" :disabled="busy||!['submitted','returned'].includes(project.formStatus)" @click="review('all','approved')"><ShieldCheck :size="15"/>批量通过</button></div><div class="table-scroll"><table class="data-table"><thead><tr><th>字段 / 填写部门</th><th>内容</th><th>审核情况</th><th v-if="user.role==='admin'">操作</th></tr></thead><tbody><tr v-for="f in FIELDS" :key="f.id"><td>{{f.label}}<div class="muted tiny">{{f.dept==='research'?'研发中心':'行政业务办'}}</div></td><td><div class="review-value">{{project.form[f.id]||'—'}}</div></td><td><span class="badge" :class="project.formReviews[f.id]?.status==='approved'?'positive':project.formReviews[f.id]?.status==='returned'?'negative':'neutral'">{{project.formReviews[f.id]?.status==='approved'?'已通过':project.formReviews[f.id]?.status==='returned'?'已退回':'待核实'}}</span><p v-if="project.formReviews[f.id]?.comment" class="sm">{{project.formReviews[f.id].comment}}</p></td><td v-if="user.role==='admin'"><div class="actions"><button class="btn btn-sm btn-soft" :disabled="busy||!['submitted','returned'].includes(project.formStatus)" @click="review(f.id,'approved')"><Check :size="12"/>通过</button><button class="btn btn-sm" :disabled="busy||!['submitted','returned'].includes(project.formStatus)" @click="review(f.id,'returned')"><RotateCcw :size="12"/>退回</button></div></td></tr></tbody></table></div><div class="panel-body"><h3 class="panel-title">修订记录</h3><div v-for="a in project.activity" :key="a.id" class="history-line"><strong>{{a.title}}</strong><span>{{a.detail}}</span><small>{{a.actor}} · {{stamp(a.time)}}</small></div></div></section>
  <section v-if="tab==='reuse'" class="panel"><div class="panel-header"><h3 class="panel-title">历史项目复用</h3></div><div class="panel-body"><div class="actions"><select v-model="sourceId" aria-label="选择历史项目"><option value="">选择历史项目</option><option v-for="p in projects.filter(p=>p.id!==project.id)" :key="p.id" :value="p.id">{{p.name}} · {{p.version}}</option></select><button class="btn" :disabled="!sourceId||busy" @click="loadReuse">查看可复用字段</button></div><div v-for="f in reuseFields" :key="f.id" class="reuse-row"><label><input type="checkbox" v-model="selected" :value="f.id"/> {{f.label}}</label><p>{{suggested[f.id]}}</p></div><div v-if="!reuseFields.length" class="empty">选择历史项目后查看可复用字段</div><button v-else class="btn btn-primary" :disabled="!selected.length" @click="applyReuse"><Copy :size="14"/>填入所选字段</button></div></section>
  <div v-if="!reviewOnly" class="actions form-footer-actions"><button class="btn" :disabled="busy||project.formStatus==='submitted'" @click="run(validate)"><FileCheck2 :size="15"/>检查填写</button><button class="btn" :disabled="busy||project.formStatus==='submitted'" @click="saveDraft"><Save :size="15"/>保存草稿</button><button class="btn btn-primary" :disabled="busy||project.formStatus==='submitted'" @click="submit"><Send :size="15"/>提交核实</button></div>
</template>
