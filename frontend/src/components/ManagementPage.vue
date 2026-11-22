<script setup>
import {ref,reactive,watch,nextTick,computed} from 'vue'
import {api,fileUrl,statusName,stamp} from '../api'
import {FIELDS} from '../fields'
const props=defineProps({section:String,user:Object,target:Object})
const emit=defineEmits(['notify','refresh'])
const users=ref([]),reviews=ref([]),selected=ref(''),busy=ref(false),editing=ref(null),showEditor=ref(false)
const visibleReviews=computed(()=>reviews.value.filter(p=>!selected.value||p.id===selected.value))
const fieldLabels=Object.fromEntries(FIELDS.map(f=>[f.id,f.label]))
const snapshots=reactive({})
const pendingReview=ref(null),reason=ref(''),reasonInput=ref(null)
const departments=['研发中心','健康医疗大数据中心','人才评价与发展中心','培训中心']
const account=reactive({username:'',password:'',displayName:'',department:'研发中心',role:'research',enabled:true})
async function load(){try{if(props.section==='users')users.value=await api('/admin/users');else reviews.value=await api('/admin/reviews')}catch(e){emit('notify',e.message,true)}}
watch(()=>props.target,async target=>{
 if(props.section!=='reviews'||!target)return
 selected.value=target.projectId
 await load()
 await nextTick()
 const section=document.getElementById(`review-${target.kind}-${target.projectId}`)
 if(section){
  section.open=true
  section.scrollIntoView({block:'start'})
 }
},{immediate:true})
if(props.section==='users'||!props.target)load()
async function loadSnapshot(event,p,h){
 if(!event.target.open||snapshots[h.id])return
 try{snapshots[h.id]=await api(`/admin/reviews/${p.id}/manual/${h.id}`)}catch(e){emit('notify',e.message,true)}
}
function edit(u){editing.value=u;Object.assign(account,u||{username:'',password:'',displayName:'',department:'研发中心',role:'research',enabled:true});if(!departments.includes(account.department))account.department='';account.password='';showEditor.value=true}
async function save(){busy.value=true;try{const r=await api('/admin/users'+(editing.value?'/'+editing.value.id:''),{method:editing.value?'PUT':'POST',body:account});showEditor.value=false;account.password='';if(r.self){window.dispatchEvent(new Event('session-expired'));return}await load();emit('notify','账号已保存，权限修改后需重新登录')}catch(e){emit('notify',e.message,true)}finally{busy.value=false}}
async function reviewed(){await load();emit('refresh')}
async function review(path, version, status){
 if(status==='returned'){
  pendingReview.value={path,version}
  reason.value=''
  await nextTick()
  reasonInput.value?.focus()
  return
 }
 await saveReview(path,version,status)
}
async function saveReview(path,version,status,comment=''){
 busy.value=true
 try{
  await api(`/projects/${path}/review`,{method:'POST',body:{...version,status,comment}})
  pendingReview.value=null
  await reviewed()
  emit('notify','审核结果已保存')
 }catch(e){
  emit('notify',e.message,true)
  if(e.status===409){
   pendingReview.value=null
   await load()
  }
 }finally{busy.value=false}
}
async function reject(){
 const {path,version}=pendingReview.value
 if(!busy.value&&reason.value.trim())await saveReview(path,version,'returned',reason.value.trim())
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
  <details :id="`review-form-${p.id}`" class="review-section">
   <summary>字段核验 · {{statusName(p.formStatus)}}</summary>
   <p v-if="p.formStatus==='returned' && p.formReviews.all?.comment">退回意见 {{p.formReviews.all.comment}}</p>
   <div class="table-scroll">
    <table class="data-table">
     <thead><tr><th>字段 / 填写部门</th><th>内容</th></tr></thead>
     <tbody><tr v-for="f in FIELDS" :key="f.id">
      <td>{{f.label}}<div class="muted tiny">{{f.dept==='research'?'研发中心':'行政业务办'}}</div></td>
      <td><div class="review-value">{{p.form[f.id]||'—'}}</div></td>
     </tr></tbody>
    </table>
   </div>
   <div v-if="p.formStatus==='submitted'" class="actions">
    <button class="btn btn-primary" :disabled="busy" @click="review(p.id+'/form',{revision:p.revision},'approved')">通过</button>
    <button class="btn" :disabled="busy" @click="review(p.id+'/form',{revision:p.revision},'returned')">不通过</button>
   </div>
   <details v-if="p.fieldHistory.length"><summary>审核历史</summary><div v-for="h in p.fieldHistory" :key="h.id" class="history-line">{{h.field==='all'?'整表':fieldLabels[h.field]||h.field}} · {{statusName(h.status)}} · {{h.comment}} · {{h.reviewer}} · {{stamp(h.time)}}</div></details>
   <details v-if="p.activity.length"><summary>修订记录</summary><div v-for="a in p.activity" :key="a.id" class="history-line"><strong>{{a.title}}</strong><span>{{a.detail}}</span><small>{{a.actor}} · {{stamp(a.time)}}</small></div></details>
  </details>
  <details :id="`review-manual-${p.id}`" class="review-section">
   <summary>操作手册 · {{statusName(p.manual.status)}}</summary>
   <p v-if="p.manual.comment">退回意见 {{p.manual.comment}}</p>
   <a v-if="p.manual.attachmentId" :href="fileUrl(p.id,p.manual.attachmentId)" class="cite-chip">下载 {{p.manual.attachmentName}}</a>
   <details v-for="(chapter,index) in p.manual.chapters" :key="index"><summary>{{chapter.title}} · {{chapter.verified?'确认无误':'待确认'}}</summary><div class="manual-review-body">{{chapter.body}}</div><img v-if="chapter.screenshot?.startsWith('data:image/')" :src="chapter.screenshot" class="image-preview" :alt="chapter.title"/></details>
   <p v-if="!p.manual.attachmentId&&!p.manual.chapters.length" class="muted">尚无手册内容</p>
   <div v-if="p.manual.status==='submitted'" class="actions"><button class="btn btn-primary" :disabled="busy" @click="review(p.id+'/manual',{revision:p.manual.revision},'approved')">通过</button><button class="btn" :disabled="busy" @click="review(p.id+'/manual',{revision:p.manual.revision},'returned')">不通过</button></div>
   <details v-for="h in p.manualHistory" :key="h.id" @toggle="loadSnapshot($event,p,h)">
    <summary>v{{h.revision}} · {{statusName(h.status)}} · {{h.reviewer}} · {{stamp(h.time)}}</summary>
    <p v-if="h.comment">{{h.comment}}</p>
    <a v-if="h.attachmentId" :href="fileUrl(p.id,h.attachmentId)" class="cite-chip">下载 {{h.attachmentName}}</a>
    <article v-for="(chapter,index) in snapshots[h.id]" :key="index"><h4>{{chapter.title}}</h4><div class="manual-review-body">{{chapter.body}}</div><img v-if="chapter.screenshot?.startsWith('data:image/')" :src="chapter.screenshot" class="image-preview" :alt="chapter.title"/></article>
   </details>
  </details>
  <details v-for="material in p.applicationMaterials" :id="`review-${material.kind}-${p.id}`" :key="material.kind" class="review-section">
   <summary>{{material.kind==='ownership'?'权属证明附件':material.label}} · {{({draft:'待送审',stale:'附件已变更，待重新送审'})[material.status]||statusName(material.status)}}</summary>
   <template v-if="material.reviewId">
    <p v-if="material.status==='stale'">{{material.name}} · v{{material.version}}</p>
    <a v-else :href="fileUrl(p.id,material.attachmentId)" class="cite-chip">下载 {{material.name}} · v{{material.version}}</a>
    <p class="muted sm">提交人 {{material.submitter}} · {{stamp(material.submittedAt)}}</p>
    <p v-if="material.reviewer" class="muted sm">审核人 {{material.reviewer}} · {{stamp(material.reviewedAt)}}</p>
    <p v-if="material.comment">{{material.comment}}</p>
    <div v-if="material.status==='submitted'" class="actions">
     <button class="btn btn-primary" :disabled="busy" @click="review(p.id+'/application-materials/'+material.kind,{reviewId:material.reviewId},'approved')">通过</button>
     <button class="btn" :disabled="busy" @click="review(p.id+'/application-materials/'+material.kind,{reviewId:material.reviewId},'returned')">不通过</button>
    </div>
   </template>
  </details>
 </section>
</template>
<div v-if="pendingReview" class="overlay" @click.self="!busy && (pendingReview=null)" @keydown.esc="!busy && (pendingReview=null)">
 <form class="modal" role="dialog" aria-modal="true" aria-labelledby="review-reason-title" @submit.prevent="reject">
  <div class="modal-head"><h3 id="review-reason-title">审核不通过</h3></div>
  <div class="modal-body">
   <div class="field">
    <label for="review-reason">不通过原因</label>
    <textarea id="review-reason" ref="reasonInput" v-model="reason" rows="4" maxlength="5000" required :disabled="busy"></textarea>
   </div>
  </div>
  <div class="modal-foot">
   <button type="button" class="btn" :disabled="busy" @click="pendingReview=null">取消</button>
   <button class="btn btn-primary" :disabled="busy||!reason.trim()">确认不通过</button>
  </div>
 </form>
</div>
<div v-if="showEditor" class="overlay" @click.self="showEditor=false"><form class="modal" @submit.prevent="save"><div class="modal-head"><h3>{{editing?'编辑账号权限':'注册账号'}}</h3><button type="button" class="btn" @click="showEditor=false">关闭</button></div><div class="modal-body"><div class="field"><label>账号</label><input v-model="account.username" :disabled="!!editing" required pattern="[A-Za-z0-9_.\-]{3,80}"/></div><div v-if="!editing" class="field"><label>初始密码（至少12位）</label><input v-model="account.password" type="password" autocomplete="new-password" minlength="12" maxlength="72" required/></div><div class="field"><label>姓名</label><input v-model="account.displayName" required maxlength="100"/></div><div class="field"><label for="account-department">部门</label><select id="account-department" v-model="account.department" required><option value="" disabled>请选择部门</option><option v-for="department in departments" :key="department">{{department}}</option></select></div><div class="field"><label>权限角色</label><select v-model="account.role"><option value="research">研发人员</option><option value="adminDept">行政业务办</option><option value="admin">管理员</option></select></div><label v-if="editing"><input type="checkbox" v-model="account.enabled"/>启用账号</label></div><div class="modal-foot"><button class="btn btn-primary" :disabled="busy">保存</button></div></form></div>
</template>


<style scoped>
.review-section {
  margin-top: 12px;
  padding: 0 16px;
  border: 1px solid #e3e7f1;
  border-radius: 10px;
}

.review-section > summary {
  padding: 12px 0;
  font-size: 14px;
  font-weight: 700;
}

.review-section[open] {
  padding-bottom: 12px;
}

.review-section > .actions {
  margin-top: 12px;
}
</style>
