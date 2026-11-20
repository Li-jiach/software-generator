// Bind the existing manual editor to the selected server-side project.
(async function connectWorkspace(){
 const projectId=new URLSearchParams(location.search).get('projectId');
 if(!projectId)return;
 const manualPath='/projects/'+encodeURIComponent(projectId)+'/manual';
 let revision=0,ready=false,savedChapters='',queue=Promise.resolve(),submitting=false;
 const localAction=actionClick;
 const api=async(path,method='GET',body)=>{
  const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(result.message||'请求失败');return result;
 };
 toast=(text,type)=>parent.postMessage({type:'workspace-toast',text,error:type==='error'},location.origin);
 const originalRender=render;
 render=function(){
  originalRender();
  document.querySelector('#view .project-head')?.remove();
  if(location.hash==='#manual')document.querySelector('#view .manual-workflow-nav')?.remove();
  document.querySelectorAll('[data-action="approveManual"],[data-action="rejectManual"]').forEach(el=>el.remove());
  document.querySelectorAll('[data-action="buildManual"],[data-action="startAnalysis"]').forEach(el=>el.remove());
  const confirm=document.querySelector('[data-action="toggleChapterVerified"]');
  if(confirm)confirm.setAttribute('aria-pressed',String(Boolean(currentChapter()?.verified)));
  const submit=document.querySelector('[data-action="submitManual"]');
  if(submit)submit.disabled=!ready||submitting||['submitted','approved'].includes(project().manual.status);
 };
 // A blur must not replace the button that the user is about to click.
 document.addEventListener('change',event=>{
  if(!['chapterTitle','chapterBody'].includes(event.target.id))return;
  event.stopImmediatePropagation();
  if(!ready||submitting||project().manual.status==='submitted')return;
  if(chapterInputSave(true)){
   const confirm=document.querySelector('[data-action="toggleChapterVerified"]');
   if(confirm){
    confirm.classList.remove('btn-confirmed');
    confirm.setAttribute('aria-pressed','false');
    if(confirm.lastChild?.nodeType===Node.TEXT_NODE)confirm.lastChild.textContent='确认无误';
   }
  }
 },true);
 function saveChapters(){
  if(!ready||project().manual.status==='submitted')return queue;
  const chapters=JSON.stringify(project().manual.chapters);
  const pending=queue.then(async()=>{
   if(chapters===savedChapters)return;
   const result=await api(manualPath,'PUT',{chapters:JSON.parse(chapters),revision});
   revision=result.revision;
   savedChapters=chapters;
  });
  queue=pending.catch(error=>{if(!submitting)toast(error.message,'error');});
  return pending;
 }
 // The connected editor stores chapter data on the server, not in the demo cache.
 save=function(){void saveChapters().catch(()=>{});};
 actionClick=async function(el){
  const action=el.dataset.action;
  if(!ready||submitting)return;
  if(['approveManual','rejectManual','confirmManualReject','downloadReceipt'].includes(action))return;
  if(['buildManual','startAnalysis'].includes(action))return toast('请在「智能生成」中使用已配置的大模型。');
  if(['openFinalConfirm','confirmSubmission'].includes(action))return toast('官网自动申报仍为流程预览');
  if(project().manual.status==='submitted'&&['saveChapter','toggleChapterVerified','addChapter','confirmAddChapter','deleteChapter','moveChapter','buildManual','startAnalysis','clearSource','uploadScreenshot'].includes(action))return toast('手册审核中，请等待管理员处理','error');
  if(['submitManual','saveChapter','toggleChapterVerified'].includes(action)){
   const title=document.querySelector('#chapterTitle'),body=document.querySelector('#chapterBody');
   if(title&&body&&(!title.value.trim()||!body.value.trim()))return toast('章节标题与正文不能为空','error');
  }
  if(action==='submitManual'){
   if(['submitted','approved'].includes(project().manual.status))return;
   submitting=true;
   try{
    chapterInputSave(true);
    render();
    await saveChapters();
    const result=await api(manualPath+'/submit','POST',{revision});
    revision=result.revision;
    Object.assign(project().manual,result,{version:revision});
    parent.postMessage({type:'workspace-manual-submitted'},location.origin);
    toast('手册已提交管理员审核');
   }catch(error){toast(error.message,'error');}
   finally{submitting=false;render();}
   return;
  }
  if(action==='saveChapter'){
   chapterInputSave(true);
   try{await saveChapters();toast('章节内容已保存');}catch{/* The save queue reports the error. */}
   render();
   return;
  }
  if(action==='toggleChapterVerified')chapterInputSave(true);
  await localAction(el);
 };
 try{
  const [p,m,u]=await Promise.all([api('/projects/'+encodeURIComponent(projectId)),api(manualPath),api('/auth/me')]);
  const initial=seedState().projects[0];
  const stored=data.projects.find(x=>x.id===projectId);
  const actual={...initial,...p,application:{...initial.application,status:'idle',step:0,receipt:null,events:[]},manual:{...initial.manual,...m,version:m.revision||1},files:p.files,source:stored?.source||{files:[],mode:'folder',hash:'',branch:'main'},analysis:stored?.analysis||{status:'idle',step:0,features:[],warnings:[]}};
  actual.manual.chapters=actual.manual.chapters.map(c=>({level:1,...c}));
  data.projects=[actual,...data.projects.filter(x=>x.id!==projectId)];data.currentId=projectId;data.role=u.role;revision=m.revision;
  data.activeChapter=m.chapters[0]?.id||'';
  savedChapters=JSON.stringify(actual.manual.chapters);
  ready=true;render();
 }catch(error){document.querySelector('.page').textContent=error.message;toast(error.message,'error');}
})();
