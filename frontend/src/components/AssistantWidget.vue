<script setup>
import {computed, nextTick, reactive, ref, watch} from 'vue'
import {Bot, Settings2, X, Send, Trash2, BookOpen, Check, Plus, FileText, ChevronDown} from 'lucide-vue-next'
import {api, assistantStream} from '../api'
const props=defineProps({project:Object,user:Object,page:String,hasUnsaved:Boolean})
const emit=defineEmits(['notify','filled'])
const open=ref(false),messages=ref([]),question=ref(''),sending=ref(false),box=ref(),settings=ref(false),settingTab=ref('model'),saving=ref(false),knowledge=ref([]),editing=ref(false),source=ref(null)
const config=reactive({base_url:'',api_key:'',model:'',reasoning_effort:'default',timeout_seconds:120,max_context_chars:16000,clear_api_key:false}),keySet=ref(false)
const doc=reactive({title:'',sourceUrl:'',content:'',enabled:true}),settingsMessage=ref('')
const projectId=computed(()=>props.project?.id||'')
const query=computed(()=>`?projectId=${encodeURIComponent(projectId.value)}`)
const live=ref(null)
const visibleTurn=computed(()=>live.value?.projectId===projectId.value?live.value:null)
const toolNames={knowledge:'软著知识检索',search_projects:'定位软著项目',project_rag:'项目资料检索',status:'查询办理状态',
 search_attachments:'查找项目附件',read_attachment:'读取附件',fill_form:'填写基础信息'}
const toolStates={running:'进行中',finished:'已完成',failed:'失败'}
let sequence=0
async function scroll(){await nextTick();if(box.value)box.value.scrollTop=box.value.scrollHeight}
async function history(){const current=++sequence;try{const rows=await api('/assistant/messages'+query.value);if(current===sequence){messages.value=rows;await scroll()}}catch(e){emit('notify',e.message,true)}}
watch(projectId,history,{immediate:true})
watch(open,()=>{if(open.value)scroll()})
async function ask(text){
 const q=String(text||question.value).trim()
 if(!q||sending.value)return
 const pid=projectId.value,page=props.page
 question.value=''
 sequence++
 live.value={projectId:pid,text:'',tools:[],phase:'正在理解问题…',error:''}
 const turn=live.value
 messages.value.push({role:'user',content:q,sources:[]})
 sending.value=true
 await scroll()
 try{
  const result=await assistantStream({question:q,projectId:pid,page,hasUnsaved:props.hasUnsaved},event=>{
   if(event.type==='delta'){turn.text+=event.text;turn.phase=''}
   if(event.type==='ready')turn.phase='正在生成回答…'
   if(event.type==='tool'){
    if(event.state==='running'){
     turn.phase=''
     turn.tools.push({name:event.name,state:event.state})
    }else{
     const tool=turn.tools.findLast(item=>item.name===event.name&&item.state==='running')
     if(tool)tool.state=event.state
    }
   }
   if(pid===projectId.value)scroll()
  })
  if(result.changed&&pid===projectId.value)emit('filled',result.project)
  if(pid===projectId.value){
   messages.value.push({role:'assistant',content:result.answer,sources:result.sources,mode:result.mode,tools:turn.tools})
  }
  live.value=null
 }catch(e){
  turn.error=e.message
  turn.phase=''
  for(const tool of turn.tools)if(tool.state==='running')tool.state='failed'
  if(pid===projectId.value&&!question.value)question.value=q
 }finally{sending.value=false;await scroll()}
}
async function clear(){if(!window.confirm('清空当前问答会话？'))return;try{await api('/assistant/messages'+query.value,{method:'DELETE'});live.value=null;await history()}catch(e){emit('notify',e.message,true)}}
async function configure(){if(props.user.role!=='admin'){emit('notify','模型配置由管理员维护',true);return}try{const c=await api('/assistant/config');for(const k of ['base_url','model','reasoning_effort','timeout_seconds','max_context_chars'])config[k]=c[k];config.api_key='';config.clear_api_key=false;keySet.value=c.api_key_set;settingsMessage.value='';settings.value=true;knowledge.value=await api('/assistant/knowledge')}catch(e){emit('notify',e.message,true)}}
async function saveConfig(test=false){saving.value=true;settingsMessage.value='';try{const c=await api('/assistant/config',{method:'PUT',body:config});keySet.value=c.api_key_set;config.api_key='';config.clear_api_key=false;settingsMessage.value='设置已保存';if(test){const r=await api('/assistant/config/test',{method:'POST'});settingsMessage.value=r.answer||'连接成功'}}catch(e){settingsMessage.value=e.message;emit('notify',e.message,true)}finally{saving.value=false}}
function editDoc(d){Object.keys(doc).forEach(k=>delete doc[k]);Object.assign(doc,d||{title:'',sourceUrl:'',content:'',enabled:true});editing.value=true}
async function saveDoc(){saving.value=true;try{await api('/assistant/knowledge'+(doc.id?'/'+doc.id:''),{method:doc.id?'PUT':'POST',body:doc});editing.value=false;knowledge.value=await api('/assistant/knowledge');emit('notify','知识资料已保存')}catch(e){emit('notify',e.message,true)}finally{saving.value=false}}
async function disableDoc(d){try{await api('/assistant/knowledge/'+d.id,{method:'DELETE'});knowledge.value=await api('/assistant/knowledge')}catch(e){emit('notify',e.message,true)}}
async function importDoc(e){const f=e.target.files?.[0];if(!f)return;if(f.size>500000){emit('notify','知识文本请控制在500KB以内',true);return}doc.content=await f.text();if(!doc.title)doc.title=f.name;e.target.value=''}
defineExpose({open:()=>{open.value=true}})
</script>
<template>
 <div class="assistant-widget"><section v-if="open" class="assistant-panel open"><div class="assistant-head"><div class="assistant-brand"><span class="assistant-brand-icon"><Bot :size="22"/></span><div><strong>软著助手</strong><small>知识搜索 · 辅助填报 · 项目检索</small></div></div><div class="assistant-head-actions"><button class="assistant-icon-btn" title="助手设置" aria-label="助手设置" @click="configure"><Settings2 :size="15"/></button><button class="assistant-icon-btn" title="清空会话" aria-label="清空会话" :disabled="sending" @click="clear"><Trash2 :size="14"/></button><button class="assistant-icon-btn" title="收起助手" aria-label="收起助手" @click="open=false"><X :size="16"/></button></div></div><div class="assistant-context"><BookOpen :size="13"/><strong>{{project?.name||'软著填报要求知识库'}}</strong></div>
 <div v-if="!messages.length" class="assistant-suggestions"><button v-for="q in ['申请软著需要哪些材料？','主要功能应该怎么填写？','源程序每页有什么要求？']" :key="q" @click="ask(q)">{{q}}</button></div><div ref="box" class="assistant-messages"><div v-if="!messages.length" class="chat-msg"><span class="chat-icon"><Bot :size="17"/></span><div class="bubble">你好，我是软著助手。可以查询登记要求、辅助填写当前项目草稿，也可以按项目名称或附件查阅资料。</div></div><div v-for="(m,i) in messages" :key="m.id||i" class="chat-msg" :class="{user:m.role==='user'}"><span v-if="m.role==='assistant'" class="chat-icon"><Bot :size="17"/></span><div class="bubble"><div>{{m.content}}</div><ul v-if="m.tools?.length" class="assistant-tools"><li v-for="(tool,index) in m.tools" :key="index">{{toolNames[tool.name]}} · {{toolStates[tool.state]}}</li></ul><div v-if="m.role==='assistant'&&m.mode==='retrieval'" class="answer-mode">知识库检索</div><button v-for="(c,j) in m.sources" :key="c.id+'-'+j" class="cite-chip" @click="source=c"><FileText :size="11"/>[{{j+1}}] {{c.name}}</button></div></div><div v-if="visibleTurn" class="chat-msg">
   <span class="chat-icon"><Bot :size="17"/></span>
   <div class="bubble">
    <div v-if="visibleTurn.text">{{visibleTurn.text}}</div>
    <p v-if="visibleTurn.phase" class="thinking" role="status">{{visibleTurn.phase}}</p>
    <ul v-if="visibleTurn.tools.length" class="assistant-tools" aria-live="polite">
     <li v-for="(tool,index) in visibleTurn.tools" :key="index" :data-state="tool.state">{{toolNames[tool.name]}} · {{toolStates[tool.state]}}</li>
    </ul>
    <p v-if="visibleTurn.error" class="field-error" role="alert">{{visibleTurn.error}}</p>
   </div>
  </div></div><form class="assistant-composer" @submit.prevent="ask()"><textarea v-model="question" placeholder="询问软著要求、填写草稿或查找项目资料…" aria-label="向软著助手提问" rows="2" maxlength="4000" :disabled="sending" @keydown.enter.exact.prevent="ask()"></textarea><button :disabled="sending||!question.trim()" aria-label="发送问题"><Send :size="17"/></button></form></section><button class="assistant-launch" :class="{active:open}" @click="open=!open"><Bot :size="19"/>软著助手</button></div>
 <div v-if="settings" class="overlay assistant-overlay" @click.self="settings=false"><section class="modal wide"><div class="modal-head"><h3>软著助手设置</h3><button class="btn icon-btn" aria-label="关闭设置" @click="settings=false"><X :size="18"/></button></div><div class="modal-body"><div class="tabs"><button :class="{active:settingTab==='model'}" @click="settingTab='model'">模型服务</button><button :class="{active:settingTab==='knowledge'}" @click="settingTab='knowledge'">填报知识库</button></div><form v-if="settingTab==='model'" @submit.prevent="saveConfig()"><div class="form-fields"><div class="field full"><label for="model-url">接口地址</label><input id="model-url" v-model="config.base_url" placeholder="http://127.0.0.1:8000/v1 或完整 /chat/completions 地址" type="url" maxlength="1000"/></div><div class="field full"><label for="model-key">API Key <span v-if="keySet" class="muted tiny">已保存，留空保留原值</span></label><input id="model-key" v-model="config.api_key" type="password" autocomplete="new-password" placeholder="输入模型服务的 Key"/><label v-if="keySet" class="sm"><input type="checkbox" v-model="config.clear_api_key"/>清除已保存 Key</label></div><div class="field"><label for="model-name">模型名</label><input id="model-name" v-model="config.model" placeholder="模型服务中的模型标识" maxlength="200"/></div><div class="field"><label for="reasoning-effort">思考深度</label><select id="reasoning-effort" v-model="config.reasoning_effort"><option value="default">默认（不发送参数）</option><option value="none">不思考 · none</option><option value="minimal">最少 · minimal</option><option value="low">低 · low</option><option value="medium">中 · medium</option><option value="high">高 · high</option><option value="xhigh">更高 · xhigh</option></select></div><div class="field"><label for="model-timeout">响应超时（秒）</label><input id="model-timeout" v-model.number="config.timeout_seconds" type="number" min="10" max="300"/></div></div><p v-if="settingsMessage" class="settings-message">{{settingsMessage}}</p><div class="actions settings-actions"><button class="btn btn-primary" :disabled="saving"><Check :size="14"/>保存设置</button><button type="button" class="btn" :disabled="saving" @click="saveConfig(true)">{{saving?'连接中…':'保存并测试连接'}}</button></div></form>
 <div v-else><div v-if="!editing"><div class="knowledge-default"><BookOpen :size="18"/><span>内置：登记材料要求、项目填报协作规范</span></div><button class="btn btn-soft" @click="editDoc()"><Plus :size="14"/>补充知识资料</button><div v-for="d in knowledge" :key="d.id" class="knowledge-row"><div><strong>{{d.title}}</strong><div class="muted tiny">v{{d.version}} · {{d.enabled?'使用中':'已停用'}}</div></div><div class="actions"><button class="btn btn-sm" @click="editDoc(d)">编辑</button><button v-if="d.enabled" class="btn btn-sm" @click="disableDoc(d)">停用</button></div></div></div><form v-else @submit.prevent="saveDoc"><div class="field"><label>资料标题</label><input v-model="doc.title" required maxlength="200"/></div><div class="field"><label>来源链接</label><input v-model="doc.sourceUrl" type="url" maxlength="1000"/></div><div class="field"><label>资料内容 <input type="file" accept=".txt,.md" @change="importDoc"/></label><textarea v-model="doc.content" required rows="12" maxlength="100000"></textarea></div><label class="sm"><input type="checkbox" v-model="doc.enabled"/>启用本资料</label><div class="actions settings-actions"><button class="btn btn-primary" :disabled="saving">保存资料</button><button type="button" class="btn" @click="editing=false">返回</button></div></form></div></div></section></div>
 <div v-if="source" class="overlay assistant-overlay" @click.self="source=null"><section class="modal"><div class="modal-head"><h3>{{source.name}}</h3><button class="btn icon-btn" aria-label="关闭来源" @click="source=null"><X :size="17"/></button></div><div class="modal-body"><pre class="text-preview">{{source.excerpt}}</pre><a v-if="source.url&&/^https?:\/\//.test(source.url)" :href="source.url" target="_blank" rel="noopener noreferrer">查看资料出处 ↗</a></div></section></div>
</template>
