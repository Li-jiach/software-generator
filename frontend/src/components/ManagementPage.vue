<script setup>
import {ref,reactive,watch,nextTick,computed} from 'vue'
import {api,fileUrl,statusName,stamp} from '../api'
import FormPage from './FormPage.vue'
import {FIELDS} from '../fields'
const props=defineProps({section:String,user:Object,target:Object})
const emit=defineEmits(['notify','refresh'])
const users=ref([]),reviews=ref([]),selected=ref(''),busy=ref(false),editing=ref(null),showEditor=ref(false)
const visibleReviews=computed(()=>reviews.value.filter(p=>!selected.value||p.id===selected.value))
const fieldLabels=Object.fromEntries(FIELDS.map(f=>[f.id,f.label]))
const snapshots=reactive({})
const departments=['研发中心','健康医疗大数据中心','人才评价与发展中心','培训中心']
const account=reactive({username:'',password:'',displayName:'',department:'研发中心',role:'research',enabled:true})
async function load(){try{if(props.section==='users')users.value=await api('/admin/users');else reviews.value=await api('/admin/reviews')}catch(e){emit('notify',e.message,true)}}
watch(()=>props.target,async target=>{
 if(props.section!=='reviews'||!target)return
 selected.value=target.projectId
 await load()
 await nextTick()
 document.getElementById(`review-${target.kind}-${target.projectId}`)?.scrollIntoView({block:'start'})
},{immediate:true})
if(props.section==='users'||!props.target)load()
async function loadSnapshot(event,p,h){
 if(!event.target.open||snapshots[h.id])return
 try{snapshots[h.id]=await api(`/admin/reviews/${p.id}/manual/${h.id}`)}catch(e){emit('notify',e.message,true)}
}
function edit(u){editing.value=u;Object.assign(account,u||{username:'',password:'',displayName:'',department:'研发中心',role:'research',enabled:true});if(!departments.includes(account.department))account.department='';account.password='';showEditor.value=true}
async function save(){busy.value=true;try{const r=await api('/admin/users'+(editing.value?'/'+editing.value.id:''),{method:editing.value?'PUT':'POST',body:account});showEditor.value=false;account.password='';if(r.self){window.dispatchEvent(new Event('session-expired'));return}await load();emit('notify','账号已保存，权限修改后需重新登录')}catch(e){emit('notify',e.message,true)}finally{busy.value=false}}
async function reviewed(){await load();emit('refresh')}
async function reviewManual(p,status){let comment='';if(status==='returned'){comment=window.prompt('退回原因');if(!comment?.trim())return}busy.value=true;try{await api('/projects/'+p.id+'/manual/review',{method:'POST',body:{status,comment,revision:p.manual.revision}});await reviewed();emit('notify','手册审核结果已保存')}catch(e){emit('notify',e.message,true)}finally{busy.value=false}}
async function reviewMaterial(p,material,status){
 let comment=''
 if(status==='returned'){
  comment=window.prompt('退回原因')
  if(!comment?.trim())return
 }
 busy.value=true
 try{
  await api(`/projects/${p.id}/application-materials/${material.kind}/review`,{method:'POST',body:{status,comment,reviewId:material.reviewId}})
  await reviewed()
  emit('notify','材料审核结果已保存')
 }catch(e){
  emit('notify',e.message,true)
  if(e.status===409)await load()
 }finally{busy.value=false}
}
</script>
<template>
<div class="page-header"><h1 class="page-title">{{section==='users'?'人员管理':'审核管理'}}</h1><button v-if="section==='users'" class="btn btn-primary" @click="edit(null)">注册账号</button><button v-else class="btn" @click="load">刷新审核列表</button></div>
<section v-if="section==='users'" class="panel"><table class="data-table"><thead><tr><th>账号</th><th>姓名</th><th>角色</th><th>部门</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="u in users" :key="u.id"><td>{{u.username}}</td><td>{{u.displayName}}</td><td>{{({admin:'管理员',adminDept:'行政业务办',research:'研发人员'})[u.role]}}</td><td>{{u.department}}</td><td>{{u.enabled?'启用':'停用'}}</td><td><button class="btn btn-sm" @click="edit(u)">编辑权限</button></td></tr></tbody></table></section>
<template v-else>
 <div class="field"><label for="review-project-select">项目筛选</label><select id="review-project-select" v-model="selected"><option value="">所有项目</option><option v-for="p in reviews" :key="p.id" :value="p.id">{{p.name}} · {{p.version}}</option></select></div>
 <p v-if="!visibleReviews.length" class="empty">暂无可显示的审核项目</p>
 <section v-for="p in visibleReviews" :key="p.id" class="management-panel review-project">
  <h2>{{p.name}} · {{p.version}}</h2>
  <section :id="`review-form-${p.id}`" class="review-section">
   <h3>人工填报全部核实 · {{statusName(p.formStatus)}}</h3>
   <FormPage :project="p" :user="user" review-only @refresh="reviewed" @notify="(...args)=>emit('notify',...args)"/>
   <details v-if="p.fieldHistory.length"><summary>字段审核历史</summary><div v-for="h in p.fieldHistory" :key="h.id" class="history-line">{{fieldLabels[h.field]||h.field}} · {{statusName(h.status)}} · {{h.comment}} · {{h.reviewer}} · {{stamp(h.time)}}</div></details>
  </section>
  <section :id="`review-manual-${p.id}`" class="review-section">
   <h3>操作手册已核实 · {{statusName(p.manual.status)}}</h3>
   <p v-if="p.manual.comment">退回意见 {{p.manual.comment}}</p>
   <details v-for="(chapter,index) in p.manual.chapters" :key="index"><summary>{{chapter.title}} · {{chapter.verified?'确认无误':'待确认'}}</summary><div class="manual-review-body">{{chapter.body}}</div><img v-if="chapter.screenshot?.startsWith('data:image/')" :src="chapter.screenshot" class="image-preview" :alt="chapter.title"/></details>
   <p v-if="!p.manual.chapters.length" class="muted">尚无手册内容</p>
   <div v-if="p.manual.status==='submitted'" class="actions"><button class="btn btn-primary" :disabled="busy" @click="reviewManual(p,'approved')">审核通过</button><button class="btn" :disabled="busy" @click="reviewManual(p,'returned')">退回修改</button></div>
   <details v-for="h in p.manualHistory" :key="h.id" @toggle="loadSnapshot($event,p,h)">
    <summary>v{{h.revision}} · {{statusName(h.status)}} · {{h.reviewer}} · {{stamp(h.time)}}</summary>
    <p v-if="h.comment">{{h.comment}}</p>
    <article v-for="(chapter,index) in snapshots[h.id]" :key="index"><h4>{{chapter.title}}</h4><div class="manual-review-body">{{chapter.body}}</div><img v-if="chapter.screenshot?.startsWith('data:image/')" :src="chapter.screenshot" class="image-preview" :alt="chapter.title"/></article>
   </details>
  </section>
  <section v-for="material in p.applicationMaterials" :id="`review-${material.kind}-${p.id}`" :key="material.kind" class="review-section">
   <h3>{{material.label}} · {{({draft:'待送审',stale:'附件已变更，待重新送审'})[material.status]||statusName(material.status)}}</h3>
   <template v-if="material.reviewId">
    <p v-if="material.status==='stale'">{{material.name}} · v{{material.version}}</p>
    <a v-else :href="fileUrl(p.id,material.attachmentId)" class="cite-chip">下载 {{material.name}} · v{{material.version}}</a>
    <p class="muted sm">提交人 {{material.submitter}} · {{stamp(material.submittedAt)}}</p>
    <p v-if="material.reviewer" class="muted sm">审核人 {{material.reviewer}} · {{stamp(material.reviewedAt)}}</p>
    <p v-if="material.comment">{{material.comment}}</p>
    <div v-if="material.status==='submitted'" class="actions">
     <button class="btn btn-primary" :disabled="busy" @click="reviewMaterial(p,material,'approved')">审核通过</button>
     <button class="btn" :disabled="busy" @click="reviewMaterial(p,material,'returned')">退回修改</button>
    </div>
   </template>
  </section>
 </section>
</template>
<div v-if="showEditor" class="overlay" @click.self="showEditor=false"><form class="modal" @submit.prevent="save"><div class="modal-head"><h3>{{editing?'编辑账号权限':'注册账号'}}</h3><button type="button" class="btn" @click="showEditor=false">关闭</button></div><div class="modal-body"><div class="field"><label>账号</label><input v-model="account.username" :disabled="!!editing" required pattern="[A-Za-z0-9_.\-]{3,80}"/></div><div v-if="!editing" class="field"><label>初始密码（至少12位）</label><input v-model="account.password" type="password" autocomplete="new-password" minlength="12" maxlength="72" required/></div><div class="field"><label>姓名</label><input v-model="account.displayName" required maxlength="100"/></div><div class="field"><label for="account-department">部门</label><select id="account-department" v-model="account.department" required><option value="" disabled>请选择部门</option><option v-for="department in departments" :key="department">{{department}}</option></select></div><div class="field"><label>权限角色</label><select v-model="account.role"><option value="research">研发人员</option><option value="adminDept">行政业务办</option><option value="admin">管理员</option></select></div><label v-if="editing"><input type="checkbox" v-model="account.enabled"/>启用账号</label></div><div class="modal-foot"><button class="btn btn-primary" :disabled="busy">保存</button></div></form></div>
</template>
