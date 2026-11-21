<script setup>
import {computed, nextTick, onMounted, onUnmounted, reactive, ref, watch} from 'vue'
import {Layers, Sparkles, FolderOpen, Receipt, FileCheck2, BookOpen, Globe, ChevronRight, ChevronsUpDown, Bell, LogOut, Menu, X, ShieldCheck, CheckCircle2, AlertCircle} from 'lucide-vue-next'
import {api, statusName} from './api'
import ProjectsPage from './components/ProjectsPage.vue'
import FormPage from './components/FormPage.vue'
import AttachmentsPage from './components/AttachmentsPage.vue'
import RecordsPage from './components/RecordsPage.vue'
import ManagementPage from './components/ManagementPage.vue'
import AssistantWidget from './components/AssistantWidget.vue'
import ManualPage from './components/ManualPage.vue'
import ApplicationPage from './components/ApplicationPage.vue'
import OfficialAccountPage from './components/OfficialAccountPage.vue'
const user=ref(null),projects=ref([]),project=ref(null),currentId=ref(localStorage.getItem('copyright-current-project')||''),route=ref('overview'),loading=ref(true),mobile=ref(false),dirty=ref(false),toasts=ref([]),modal=ref(''),projectEditing=ref(null),busy=ref(false),notifications=ref([])
const login=reactive({username:'admin',password:''}),loginError=ref('')
const projectForm=reactive({name:'',version:'V1.0',dept:'研发中心',owner:'',description:'',allowedRoles:['adminDept','research']})
const nav=[{name:'软著项目管理',icon:Layers,items:[['overview','软著查阅',FolderOpen],['attachments','附件资料',FolderOpen],['records','申报记录',Receipt]]},{name:'材料智能生成',icon:Sparkles,items:[['basic','基础信息填报',FileCheck2],['source','操作手册生成',BookOpen],['rpa','官网自动申报',Globe]]}]
nav.push({name:'管理页面',icon:ShieldCheck,items:[['users','人员管理',Menu],['reviews','审核管理',ShieldCheck],['official-account','官网账号',Globe]]})
const visibleNav=computed(()=>nav.filter(n=>n.name!=='管理页面'||user.value?.role==='admin'))
const expanded=ref(nav.map(n=>n.name))
const reviewTarget=ref(null),manualEntry=ref('source')
const titles={users:'人员管理',reviews:'审核管理','official-account':'官网账号',overview:'软著查阅',records:'申报记录',basic:'基础信息填报',attachments:'附件资料',source:'操作手册生成',rpa:'官网自动申报'}
const parent=computed(()=>nav.find(n=>n.items.some(i=>i[0]===route.value))?.name||'软著项目管理')
function notify(text,error=false){const id=Date.now()+Math.random();toasts.value.push({id,text,error});setTimeout(()=>toasts.value=toasts.value.filter(t=>t.id!==id),5000)}
function safeLeave(){return !dirty.value||window.confirm('当前填报尚未保存，确认离开？')}
function canNavigate(to){return Object.hasOwn(titles,to)&&(!['users','reviews','official-account'].includes(to)||user.value?.role==='admin')}
function navigate(to){if(!canNavigate(to)||!safeLeave())return false;dirty.value=false;route.value=to;location.hash=to;mobile.value=false;window.scrollTo(0,0);return true}
async function selectProject(id,to){if(!safeLeave())return;try{const p=await api('/projects/'+encodeURIComponent(id));project.value=p;currentId.value=id;localStorage.setItem('copyright-current-project',id);dirty.value=false;if(to)navigate(to)}catch(e){notify(e.message,true)}}
async function refresh(){try{projects.value=await api('/projects');const selected=projects.value.find(p=>p.id===currentId.value)||projects.value[0];if(selected){currentId.value=selected.id;project.value=await api('/projects/'+selected.id);localStorage.setItem('copyright-current-project',selected.id)}else{project.value=null;currentId.value='';if(!['users','reviews','official-account'].includes(route.value))route.value='overview'}}catch(e){notify(e.message,true)}}
async function signIn(){busy.value=true;loginError.value='';try{await api('/auth/login',{method:'POST',body:login});login.password='';user.value=await api('/auth/me');await refresh()}catch(e){loginError.value=e.message}finally{busy.value=false}}
async function logout(){if(!safeLeave())return;try{await api('/auth/logout',{method:'POST'})}catch{}user.value=null;project.value=null;projects.value=[];dirty.value=false}
function editProject(p=null){projectEditing.value=p;Object.assign(projectForm,{name:p?.name||'',version:p?.version||'V1.0',dept:p?.dept||user.value.department,owner:p?.owner||user.value.displayName,description:p?.description||'',allowedRoles:p?.allowedRoles||['adminDept','research']});modal.value='project'}
async function saveProject(){busy.value=true;try{const p=await api('/projects'+(projectEditing.value?'/'+projectEditing.value.id:''),{method:projectEditing.value?'PUT':'POST',body:{...projectForm,revision:projectEditing.value?.revision}});modal.value='';currentId.value=p.id;await refresh();notify(projectEditing.value?'项目资料已更新':'软著项目已创建')}catch(e){notify(e.message,true)}finally{busy.value=false}}
async function archive(p){if(!window.confirm(`归档项目「${p.name}」？`))return;try{await api('/projects/'+p.id,{method:'DELETE'});await refresh();notify('项目已归档')}catch(e){notify(e.message,true)}}
async function loadNotifications(){const account=user.value?.id;if(!account)return;const rows=await api('/notifications');if(user.value?.id===account)notifications.value=rows}
function updateNotifications(){loadNotifications().catch(()=>{})}
async function showNotifications(){try{await loadNotifications();modal.value='notifications'}catch(e){notify(e.message,true)}}
function openTask(n){
 if(user.value.role==='admin'){
  if(navigate('reviews')){reviewTarget.value=n;modal.value=''}
 }else{
  modal.value='';manualEntry.value=n.kind==='manual'?'manual':'source';selectProject(n.projectId,({manual:'source',source:'attachments',ownership:'attachments'})[n.kind]||'basic')
 }
}
const formPage=ref(null)
async function showAssistantFill(saved){
 if(saved.id!==project.value?.id||saved.revision<=project.value.revision)return
 if(dirty.value){notify('助手已保存参考草稿。当前页面有未保存的修改，请先保留你的输入再刷新。',true);return}
 const field=saved.assistantReferenceFields.find(key=>saved.form[key]!==project.value.form[key])
 receiveRefresh(saved)
 await nextTick()
 if(field&&route.value==='basic')formPage.value?.showAssistantField(field)
}
function receiveRefresh(saved){
 dirty.value=false
 if(saved?.id===currentId.value){project.value=saved;projects.value=projects.value.map(p=>p.id===saved.id?{...p,name:saved.name,version:saved.version,revision:saved.revision,formStatus:saved.formStatus}:p)}
 else if(!saved)refresh()
 updateNotifications()
}
function handleWorkflowMessage(e){
 if(e.origin!==location.origin||e.source!==document.querySelector('.workflow-frame')?.contentWindow)return
 if(e.data?.type==='workspace-toast')notify(e.data.text,e.data.error)
 if(e.data?.type==='workspace-manual-submitted')updateNotifications()
}
window.addEventListener('message',handleWorkflowMessage)
window.addEventListener('session-expired',()=>{user.value=null;project.value=null;projects.value=[]})
window.addEventListener('beforeunload',e=>{if(dirty.value){e.preventDefault();e.returnValue=''}})
function syncRoute(){const r=location.hash.slice(1);route.value=canNavigate(r)?r:'overview'}
window.addEventListener('hashchange',syncRoute)
watch(user,u=>{if(u){syncRoute();updateNotifications()}else{route.value='overview';modal.value='';notifications.value=[];reviewTarget.value=null}})
const notificationTimer=setInterval(updateNotifications,15000)
onUnmounted(()=>{clearInterval(notificationTimer);window.removeEventListener('message',handleWorkflowMessage);window.removeEventListener('hashchange',syncRoute)})
onMounted(async()=>{try{user.value=await api('/auth/me');await refresh()}catch{}finally{loading.value=false}})
</script>
<template>
 <div v-if="loading" class="boot-screen"><Sparkles :size="30"/><p>正在载入工作空间…</p></div>
 <main v-else-if="!user" class="login-screen"><form class="login-card" @submit.prevent="signIn"><div class="brand-mark"><Sparkles :size="24"/></div><h1>知产协同</h1><p>软件著作权工作空间</p><div class="field"><label for="username">账号</label><input id="username" v-model="login.username" autocomplete="username" required maxlength="80"/></div><div class="field"><label for="password">密码</label><input id="password" v-model="login.password" type="password" autocomplete="current-password" required maxlength="200"/></div><p v-if="loginError" class="field-error">{{loginError}}</p><button class="btn btn-primary" :disabled="busy">{{busy?'登录中…':'登录工作空间'}}</button></form></main>
 <template v-else><div class="app"><aside class="sidebar" :class="{visible:mobile}"><div class="brand"><div class="brand-mark"><Sparkles :size="23"/></div><button class="mobile-close" aria-label="关闭导航" @click="mobile=false"><X :size="18"/></button></div><div class="nav-caption">工作空间</div><nav><div v-for="group in visibleNav" :key="group.name" class="nav-group"><button class="nav-parent" :class="{active:parent===group.name,open:expanded.includes(group.name)}" @click="expanded=expanded.includes(group.name)?expanded.filter(n=>n!==group.name):[...expanded,group.name]"><component :is="group.icon" :size="18"/>{{group.name}}<ChevronRight class="chevron" :size="14"/></button><div v-show="expanded.includes(group.name)" class="nav-children"><button v-for="item in group.items" :key="item[0]" class="nav-child" :class="{active:route===item[0]||(route==='attachments'&&item[0]==='overview')}" @click="navigate(item[0])"><span class="nav-label"><component :is="item[2]" :size="14"/>{{item[1]}}</span><span v-if="route===item[0]" class="tiny-dot"></span></button></div></div></nav><div class="nav-foot"><div class="side-bottom"><span class="online"></span><span>{{user.displayName}}</span></div></div></aside>
 <div class="main"><header class="topbar"><div class="breadcrumb"><button class="top-action mobile-open" aria-label="打开导航" @click="mobile=true"><Menu :size="18"/></button><span>{{parent}}</span><ChevronRight :size="12"/><span class="current">{{titles[route]}}</span></div><div class="top-actions"><div class="project-picker"><Layers :size="15" aria-hidden="true"/><select aria-label="当前项目" :value="currentId" :disabled="!projects.length" @change="selectProject($event.target.value)"><option v-if="!projects.length" value="">尚无项目</option><option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}} · {{p.version}}</option></select><ChevronsUpDown :size="14" aria-hidden="true"/></div><span class="account-role">{{user.role==='admin'?'管理员':user.department}}</span><button class="top-action" title="待办事项" :aria-label="notifications.length?`待办事项，${notifications.length}项`:'待办事项'" @click="showNotifications"><Bell :size="17"/><span v-if="notifications.length" class="noti" aria-hidden="true"></span></button><button class="top-action" title="退出登录" aria-label="退出登录" @click="logout"><LogOut :size="16"/></button><div class="avatar" :title="user.displayName">{{user.role==='admin'?'AD':user.displayName.slice(0,1)}}</div></div></header>
 <main class="page fade">
  <ProjectsPage v-if="route==='overview'" :projects="projects" :user="user" @create="editProject()" @edit="editProject" @archive="archive" @open="selectProject"/>
  <ManagementPage v-else-if="['users','reviews'].includes(route)&&user.role==='admin'" :key="route" :section="route" :user="user" :target="reviewTarget" @notify="notify" @refresh="receiveRefresh"/>
  <OfficialAccountPage v-else-if="route==='official-account'&&user.role==='admin'" @notify="notify"/>
  <template v-else-if="project">
   <FormPage ref="formPage" v-if="route==='basic'" :key="project.id" :project="project" :user="user" :projects="projects" @dirty="dirty=$event" @refresh="receiveRefresh" @notify="notify"/>
   <AttachmentsPage v-else-if="route==='attachments'" :key="project.id" :project="project" @refresh="receiveRefresh" @notify="notify"/>
   <RecordsPage v-else-if="route==='records'" :key="project.id" :project="project" :user="user" @refresh="receiveRefresh" @notify="notify"/>
   <ManualPage v-else-if="route==='source'" :key="project.id+manualEntry" :project="project" :user="user" :edit-first="manualEntry==='manual'" @refresh="receiveRefresh" @notify="notify"/>
   <ApplicationPage v-else-if="route==='rpa'" :key="project.id" :project="project" @notify="notify" @navigate="navigate"/>
  </template>
  <section v-else class="panel empty"><FolderOpen :size="32"/><strong>请先创建或选择软著项目</strong><button class="btn btn-primary" @click="editProject()">新建软著项目</button></section>
 </main></div></div>
 <AssistantWidget :project="project" :user="user" :page="route" :has-unsaved="dirty" @filled="showAssistantFill" @notify="notify"/>
 <div v-if="modal==='project'" class="overlay" @click.self="modal=''"><form class="modal" @submit.prevent="saveProject"><div class="modal-head"><h3>{{projectEditing?'编辑项目资料':'创建软著项目'}}</h3><button type="button" class="btn icon-btn" aria-label="关闭" @click="modal=''"><X :size="18"/></button></div><div class="modal-body form-fields"><div class="field full"><label for="pName">软件项目名称 <span class="required">*</span></label><input id="pName" v-model="projectForm.name" required maxlength="200"/></div><div class="field"><label for="pVersion">版本号</label><input id="pVersion" v-model="projectForm.version" required maxlength="80"/></div><div class="field"><label for="pDept">承担部门</label><input id="pDept" v-model="projectForm.dept" required maxlength="100"/></div><div class="field"><label for="pOwner">负责人</label><input id="pOwner" v-model="projectForm.owner" required maxlength="100"/></div><div class="field full"><label for="pDescription">项目说明</label><textarea id="pDescription" v-model="projectForm.description" rows="3" maxlength="5000"></textarea></div><div v-if="projectEditing&&user.role==='admin'" class="field full"><label>允许访问的部门</label><div class="actions"><label><input type="checkbox" v-model="projectForm.allowedRoles" value="adminDept"/>行政业务办</label><label><input type="checkbox" v-model="projectForm.allowedRoles" value="research"/>研发中心</label></div></div></div><div class="modal-foot"><button type="button" class="btn" @click="modal=''">取消</button><button class="btn btn-primary" :disabled="busy">{{busy?'保存中…':'保存项目'}}</button></div></form></div>
 <div v-if="modal==='notifications'" class="overlay" @click.self="modal=''"><section class="modal"><div class="modal-head"><h3>待办事项</h3><button class="btn icon-btn" aria-label="关闭待办" @click="modal=''"><X :size="18"/></button></div><div class="modal-body"><button v-for="n in notifications" :key="n.projectId+n.kind" class="task-row" @click="openTask(n)"><span>{{n.name}}</span><span class="badge warning">{{statusName(n.status)}}</span></button><div v-if="!notifications.length" class="empty">暂无待办事项</div></div></section></div>
 </template>
 <div class="toast-area" aria-live="polite"><div v-for="t in toasts" :key="t.id" class="toast" :class="{error:t.error}"><AlertCircle v-if="t.error" :size="17"/><CheckCircle2 v-else :size="17"/><span>{{t.text}}</span></div></div>
</template>
