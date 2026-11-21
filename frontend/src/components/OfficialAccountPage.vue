<script setup>
import {onMounted, ref} from 'vue'
import {api} from '../api'

const emit=defineEmits(['notify'])
const username=ref(''),password=ref(''),configured=ref(false),busy=ref(true),error=ref('')

onMounted(async()=>{
 try{
  const account=await api('/admin/official-credentials')
  username.value=account.username
  configured.value=account.configured
 }catch(e){error.value=e.message}
 finally{busy.value=false}
})

async function save(){
 busy.value=true
 error.value=''
 try{
  await api('/admin/official-credentials',{method:'PUT',body:{username:username.value,password:password.value}})
  configured.value=true
  password.value=''
  emit('notify','官网机构账号已保存')
 }catch(e){error.value=e.message}
 finally{busy.value=false}
}
</script>

<template>
 <div class="page-header"><h1 class="page-title">官网账号</h1></div>
 <form class="panel" @submit.prevent="save">
  <div class="panel-header"><h2 class="panel-title">中国版权保护中心机构管理员账号</h2></div>
  <div class="panel-body field">
   <p class="muted sm">{{configured?'已配置官网账号。如需更新，请重新输入官网密码。':'系统管理员启动官网申报时可使用此账号登录。'}}</p>
   <label for="official-username">机构管理员账号</label>
   <input id="official-username" v-model="username" autocomplete="off" required maxlength="200" :disabled="busy"/>
   <label for="official-password">官网密码</label>
   <input id="official-password" v-model="password" type="password" autocomplete="new-password" required maxlength="256" :disabled="busy"/>
   <p v-if="error" class="field-error" role="alert">{{error}}</p>
   <div class="actions"><button class="btn btn-primary" :disabled="busy">保存账号</button></div>
  </div>
 </form>
</template>
