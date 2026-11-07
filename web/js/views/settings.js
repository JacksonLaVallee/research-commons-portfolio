import * as api from '../api.js';
import {state} from '../store.js';
import {h,clear,section,button,toast} from '../ui.js';
import {head} from './common.js';

export async function render(el){
  const [settings,projects]=await Promise.all([api.get('/api/settings'),api.get('/api/projects')]);
  const name=h('input',{value:state.project.name}); const question=h('textarea',{rows:3},state.project.question);
  const key=h('input',{type:'password',autocomplete:'off',placeholder:settings.has_key?'Key is stored; leave blank to retain it':'Paste your Amplify key'});
  const base=h('input',{value:settings.base_url}); const model=h('input',{value:settings.model,placeholder:'Choose a model ID from the available models'});
  const ir=h('input',{type:'number',min:0,step:'any',value:settings.input_rate,placeholder:'Input price per million tokens'});
  const or=h('input',{type:'number',min:0,step:'any',value:settings.output_rate,placeholder:'Output price per million tokens'});
  const budget=h('input',{type:'number',min:.01,max:5,step:.01,value:settings.budget_usd}); const models=h('div');
  el.append(head('Projects & settings','Project data stays on this computer. AI tools use your configured Amplify deployment.'),
    h('div',{class:'grid2'},section('Your projects',h('ul',{class:'list'},projects.projects.map(p=>h('li',{},h('a',{href:`/?project=${encodeURIComponent(p.id)}#/home`},p.name),p.id===api.PROJECT_ID?' · current':''))),
      h('label',{},'Name',name),h('label',{},'Research question',question),h('div',{class:'row'},
      button('Save project',async()=>{await api.post('/api/project',{name:name.value,question:question.value});location.reload();},'primary'),
      button('Create as new project',async()=>{const r=await api.post('/api/projects',{name:name.value,question:question.value});location.href=`/?project=${r.project_id}#/home`;}))),
    section('Amplify connection',h('div',{class:'callout'},settings.ready?'Ready for live AI analysis':'Configure the connection to enable AI analysis'),
      h('div',{class:'stack'},h('label',{},'API key',key),h('label',{},'Base URL',base),h('label',{},'Model ID',model),
      h('label',{},'Input USD / million tokens',ir),h('label',{},'Output USD / million tokens',or),h('label',{},'Local budget ceiling (USD, across all projects)',budget),
      h('p',{class:'muted small'},`Reserved: $${settings.reserved_usd.toFixed(4)} across ${settings.calls} calls. Reservations are conservative estimates, not the provider's billing balance. Failed calls retain their reservation.`),
      button('Save connection',async()=>{try{await api.post('/api/settings',{AMPLIFY_API_KEY:key.value,AMPLIFY_BASE_URL:base.value,AMPLIFY_MODEL:model.value,AMPLIFY_INPUT_USD_PER_MILLION:ir.value,AMPLIFY_OUTPUT_USD_PER_MILLION:or.value,VRP_BUDGET_USD:budget.value});key.value='';toast('Connection saved','ok');}catch(e){toast(e.message,'bad');}},'primary'),
      button('Check connection / list models',async()=>{try{const r=await api.get('/api/models');clear(models,h('pre',{class:'model-list'},JSON.stringify(r,null,2)));}catch(e){clear(models,h('p',{class:'callout bad'},e.message));}},'sm'),models))),
    section('Start here',h('ol',{},h('li',{},'Upload documents and CSV files in Library, or search current literature.'),h('li',{},'Review extracted claims and their source quotations.'),h('li',{},'Audit assumptions, propose a recipe, review and approve it, then run it.'),h('li',{},'Export a reproducible run bundle and an evidence-linked brief.')),
      h('p',{class:'muted small'},'Public literature and funding searches work without an Amplify key. The project starts empty; demonstrations use explicitly identified real datasets.')));
}
