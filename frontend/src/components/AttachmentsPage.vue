<script setup>
import {computed, reactive, ref} from 'vue'
import {Upload, File, Eye, Download, Trash2, RefreshCw, History, X} from 'lucide-vue-next'
import {api, fileUrl, size, stamp, statusName} from '../api'
const props=defineProps({project:Object})
const emit=defineEmits(['refresh','notify'])
const input=ref(),replacement=ref(null),category=ref('其他附件'),filter=ref('all'),preview=ref(null),busy=ref(false),versions=ref(false)
const categories=['申请表','权属材料','操作手册','源程序','源程序鉴别材料','技术文档','回执证书','其他附件']
const materialFiles=reactive({source:'',ownership:''})
const sending=ref(false)
const files=computed(()=>{
 let rows=props.project.files.filter(f=>filter.value==='all'||f.type===filter.value)
 if(!versions.value){const seen=new Set();rows=rows.filter(f=>{if(seen.has(f.name))return false;seen.add(f.name);return true})}
 return rows
})
async function upload(list){
 if(busy.value||!list.length)return
 const target=replacement.value, categoryName=target?.type||category.value, projectId=props.project.id
 busy.value=true
 let done=0
 try{
  for(const file of list){
   const zip=/\.zip$/i.test(file.name)
   if(target&&zip!==/\.zip$/i.test(target.name))throw new Error('新版本与原附件须同为 ZIP，或同为非 ZIP 文件')
   if(!file.size||(!zip&&file.size>20*1024*1024))throw new Error(`${file.name}：请上传非空文件，非 ZIP 文件上限 20 MB`)
   const body=new FormData()
   body.append('file',file,target?.name||file.name);body.append('category',categoryName)
   await api(`/projects/${projectId}/files`,{method:'POST',body})
   done++
  }
  emit('notify',`已上传 ${done} 份附件`)
 }catch(e){emit('notify',done?`已上传 ${done} 份。${e.message}`:e.message,true)}
 finally{replacement.value=null;busy.value=false;if(input.value)input.value.value='';if(done)emit('refresh')}
}
async function show(f){try{if(f.contentType==='application/pdf'||f.contentType.startsWith('image/'))preview.value={...f,media:true};else{const r=await api(`/projects/${props.project.id}/files/${f.id}/text`);preview.value={...f,text:r.text||r.warning||'该格式请下载原件查看'}}}catch(e){emit('notify',e.message,true)}}
async function remove(f){if(!window.confirm(`移除附件「${f.name}」？`))return;try{await api(`/projects/${props.project.id}/files/${f.id}`,{method:'DELETE'});emit('refresh');emit('notify','附件已移除')}catch(e){emit('notify',e.message,true)}}
async function reextract(f){try{const r=await api(`/projects/${props.project.id}/files/${f.id}/extract`,{method:'POST'});emit('notify',r.warning||'检索文本已更新');emit('refresh')}catch(e){emit('notify',e.message,true)}}
async function submitMaterial(material){
 if(sending.value||!materialFiles[material.kind])return
 sending.value=true
 try{
  await api(`/projects/${props.project.id}/application-materials/${material.kind}/submit`,{method:'POST',body:{attachmentId:materialFiles[material.kind]}})
  materialFiles[material.kind]=''
  emit('refresh')
  emit('notify','材料已提交管理员审核')
 }catch(e){emit('notify',e.message,true)}
 finally{sending.value=false}
}
</script>
<template>
 <div class="page-header"><h1 class="page-title sr-only">附件资料</h1><button class="btn btn-primary" :disabled="busy" @click="replacement=null;input.click()"><Upload :size="16"/>上传资料</button></div>
 <section class="panel"><div class="panel-body"><div class="actions"><label for="fileCategory" class="sm">资料分类</label><select id="fileCategory" v-model="category"><option v-for="c in categories" :key="c">{{c}}</option></select><span class="muted sm">支持ZIP压缩包，ZIP不限大小；PDF、Word、文本及图片上限20MB</span></div><div class="space"></div><div class="dropzone" :class="{disabled:busy}" @dragover.prevent @drop.prevent="!busy&&upload($event.dataTransfer.files)" @click="!busy&&(replacement=null,input.click())"><Upload :size="27"/><strong>{{busy?'正在保存附件…':'点击或拖拽上传附件'}}</strong></div><input ref="input" type="file" multiple hidden @change="upload($event.target.files)"/></div></section><div class="space"></div>
 <section class="panel"><div class="toolbar"><div class="filters"><button class="filter" :class="{active:filter==='all'}" @click="filter='all'">全部资料</button><button v-for="c in categories" :key="c" class="filter" :class="{active:filter===c}" @click="filter=c">{{c}}</button></div><label class="sm"><input type="checkbox" v-model="versions"/> 显示历史版本</label></div><div class="table-scroll"><table class="data-table"><thead><tr><th>文件名称</th><th>分类 / 版本</th><th>大小</th><th>上传时间</th><th>操作</th></tr></thead><tbody><tr v-for="f in files" :key="f.id"><td><div class="file-row"><span class="file-type"><File :size="18"/></span><div><strong class="em">{{f.name}}</strong><div v-if="f.warning" class="muted tiny">{{f.warning}}</div></div></div></td><td>{{f.type}}<span class="tag">v{{f.version}}</span></td><td>{{size(f.size)}}</td><td>{{stamp(f.uploaded)}}</td><td><div class="actions"><button class="btn btn-sm icon-btn" title="预览附件" @click="show(f)"><Eye :size="14"/></button><a class="btn btn-sm icon-btn" title="下载原件" :href="fileUrl(project.id,f.id)"><Download :size="14"/></a><button class="btn btn-sm icon-btn" title="上传新版本" :disabled="busy" @click="replacement=f;input.click()"><History :size="14"/></button><button class="btn btn-sm icon-btn" title="重新提取文本" @click="reextract(f)"><RefreshCw :size="14"/></button><button class="btn btn-sm icon-btn" title="移除附件" @click="remove(f)"><Trash2 :size="14"/></button></div></td></tr><tr v-if="!files.length"><td colspan="5"><div class="empty">尚无该类附件</div></td></tr></tbody></table></div></section>
 <section class="panel application-panel">
  <div class="panel-header"><h2 class="panel-title">申报附件送审</h2></div>
  <div class="panel-body">
   <div v-for="material in project.applicationMaterials" :key="material.kind" class="application-check">
    <div>
     <strong>{{material.label}}</strong>
     <p class="sm muted">{{({draft:'待送审',stale:'附件已变更，待重新送审'})[material.status]||statusName(material.status)}}<template v-if="material.name"> · {{material.name}} · v{{material.version}}</template></p>
     <p v-if="material.status==='returned'" class="field-error">{{material.comment}}</p>
    </div>
    <form class="actions" @submit.prevent="submitMaterial(material)">
     <select v-model="materialFiles[material.kind]" :aria-label="`选择${material.category}`" :disabled="!material.candidates.length||sending" required>
      <option value="" disabled>{{material.candidates.length?'请选择附件':`请上传「${material.category}」分类的文件`}}</option>
      <option v-for="file in material.candidates" :key="file.id" :value="file.id" :disabled="file.id===material.attachmentId&&['submitted','approved'].includes(material.status)">{{file.name}} · v{{file.version}}</option>
     </select>
     <button class="btn btn-sm" :disabled="!materialFiles[material.kind]||sending">提交审核</button>
    </form>
   </div>
  </div>
 </section>
 <div v-if="preview" class="overlay" @click.self="preview=null"><div class="modal wide"><div class="modal-head"><h3>{{preview.name}}</h3><button class="btn icon-btn" aria-label="关闭预览" @click="preview=null"><X :size="18"/></button></div><div class="modal-body"><iframe v-if="preview.media&&preview.contentType==='application/pdf'" :src="fileUrl(project.id,preview.id,true)" class="file-preview" title="PDF附件预览"></iframe><img v-else-if="preview.media" :src="fileUrl(project.id,preview.id,true)" class="image-preview" :alt="preview.name"/><pre v-else class="text-preview">{{preview.text}}</pre></div></div></div>
</template>
