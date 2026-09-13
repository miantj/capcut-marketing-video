'use strict';
const $ = (id) => document.getElementById(id);
const state = {videos: [], music: null, jobs: [], revision: null, busy: false, health: null, detail: null};
const labels = {uploading: '待上传', queued: '排队中', processing: '制作中', ready: '可下载', needs_attention: '需要处理', cancelled: '已取消'};
const templates = {new: '新品上新', selling: '卖点介绍', promo: '活动促销'};
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const size = (bytes) => bytes >= 1024 ** 3 ? (bytes / 1024 ** 3).toFixed(2) + ' GB' : (bytes / 1024 ** 2).toFixed(1) + ' MB';
const date = (seconds) => new Date(seconds * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const artifact = (job, name) => `/api/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(name)}`;
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
function formError(message) { $('form-error').textContent = message; $('form-error').hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}});
  if (response.status === 401 && !$('login-dialog').open) $('login-dialog').showModal();
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(x => `${x.loc?.at(-1) || ''}：${x.msg}`).join('；') : data.detail;
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return data;
}
function body() {
  return {title: $('title').value.trim(), owner: $('owner').value.trim(), script: $('script').value.trim(),
    template: document.querySelector('[name=template]:checked').value, ratio: $('ratio').value,
    selection: $('selection').value, narration: $('narration').value,
    tts_speaker: $('narration').value === 'none' ? 'zh_female_vv_uranus_bigtts' : ($('tts-voice').value === 'custom' ? $('tts-speaker').value.trim() : $('tts-voice').value),
    tts_speed: Number($('tts-speed').value), bgm_volume: Number($('volume').value) / 100,
    allow_cloud_analysis: $('allow-cloud').checked};
}
function renderFiles() {
  $('video-list').innerHTML = state.videos.map((file, i) => `<li class="file-row"><span class="file-name">${i+1}. ${esc(file.name)}</span><span class="file-size">${size(file.size)}</span><button type="button" data-move="${i}" data-direction="-1" aria-label="上移 ${esc(file.name)}" ${i === 0 ? 'disabled' : ''}>↑</button><button type="button" data-move="${i}" data-direction="1" aria-label="下移 ${esc(file.name)}" ${i === state.videos.length - 1 ? 'disabled' : ''}>↓</button><button type="button" data-remove="${i}" aria-label="移除 ${esc(file.name)}">×</button></li>`).join('');
  $('music-label').textContent = state.music?.name || '添加背景音乐';
  $('music-meta').textContent = state.music ? size(state.music.size) : '选择一首音乐 · MP3 / WAV / M4A 等';
}
function addVideos(files) {
  if (state.busy || state.revision) return;
  const incoming = Array.from(files);
  if (state.videos.length + incoming.length > 20) return formError('最多选择 20 段视频。');
  if (incoming.some(f => !/\.(mp4|mov|m4v|webm)$/i.test(f.name))) return formError('视频支持 MP4、MOV、M4V、WEBM 格式。');
  if (incoming.some(f => f.size > 1024 ** 3 || !f.size)) return formError('请上传非空视频，单文件最多 1GB。');
  state.videos.push(...incoming); renderFiles(); formError('');
}
function addMusic(files) {
  if (state.busy || state.revision) return;
  const file = Array.from(files)[0];
  if (!file) return;
  if (!/\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(file.name) || !file.size || file.size > 1024 ** 3) return formError('请选择有效音乐文件，单文件最多 1GB。');
  state.music = file; renderFiles(); formError('');
}
$('videos').addEventListener('change', e => { addVideos(e.target.files); e.target.value = ''; });
$('music').addEventListener('change', e => { addMusic(e.target.files); e.target.value = ''; });
for (const [id, handler, input] of [['video-drop', addVideos, 'videos'], ['music-drop', addMusic, 'music']]) {
  const zone = $(id);
  zone.addEventListener('keydown', e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); $(input).click();}});
  zone.addEventListener('dragover', e => {e.preventDefault(); zone.classList.add('drag');});
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', e => {e.preventDefault(); zone.classList.remove('drag'); handler(e.dataTransfer.files);});
}
$('video-list').addEventListener('click', e => {
  if (state.busy) return;
  const button = e.target.closest('button'); if (!button) return;
  if (button.dataset.remove !== undefined) state.videos.splice(Number(button.dataset.remove), 1);
  if (button.dataset.move !== undefined) {
    const index = Number(button.dataset.move), other = index + Number(button.dataset.direction);
    if (other >= 0 && other < state.videos.length) [state.videos[index], state.videos[other]] = [state.videos[other], state.videos[index]];
  }
  renderFiles();
});
$('script').addEventListener('input', () => $('word-count').textContent = `${$('script').value.length} / 3000`);
$('volume').addEventListener('input', () => $('volume-value').textContent = `${$('volume').value}%`);
function updateNarration() {
  const enabled = $('narration').value === 'volcengine';
  $('tts-settings').hidden = !enabled;
  $('tts-custom-row').hidden = $('tts-voice').value !== 'custom';
  $('tts-speaker').required = enabled && $('tts-voice').value === 'custom';
  $('production-note').textContent = enabled ? '自动生成口播；接口不可用时自动回退为字幕 + 背景音乐。原视频静音。' : '不生成口播，按原流程制作字幕 + 背景音乐，原视频静音。';
  $('timing-note').textContent = enabled ? '保留原文 · 字幕按实际口播时长对齐' : '保留原文 · 时长为文字估算，未对齐配音';
}
$('narration').addEventListener('change', updateNarration);
$('tts-voice').addEventListener('change', updateNarration);
let speechPreviewUrl, speechPreviewController;
function clearSpeechPreview() {
  speechPreviewController?.abort(); speechPreviewController = null;
  $('tts-preview-audio').pause(); $('tts-preview-audio').removeAttribute('src');
  $('tts-preview-result').hidden = true; $('tts-preview-download').removeAttribute('href');
  if (speechPreviewUrl) { URL.revokeObjectURL(speechPreviewUrl); speechPreviewUrl = null; }
  $('tts-preview').disabled = state.busy;
  $('tts-preview').textContent = '生成试听（前 20 字）';
}
for (const id of ['script','narration','tts-voice','tts-speaker','tts-speed']) $(id).addEventListener('input', clearSpeechPreview);
$('tts-preview').addEventListener('click', async () => {
  const request = body();
  if (!request.script) return formError('请先输入文案，再生成试听。');
  clearSpeechPreview();
  const controller = new AbortController(); speechPreviewController = controller;
  const button = $('tts-preview'); button.disabled = true; button.textContent = '正在生成试听…';
  try {
    const response = await fetch('/api/tts/preview', {method:'POST', signal:controller.signal, headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:Array.from(request.script).slice(0,20).join(''), speaker:request.tts_speaker, speed:request.tts_speed})});
    if (response.status === 401 && !$('login-dialog').open) $('login-dialog').showModal();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : '试听生成失败，请检查文案、音色和语速。');
    }
    const blob = await response.blob();
    if (controller !== speechPreviewController) return;
    speechPreviewUrl = URL.createObjectURL(blob);
    $('tts-preview-audio').src = speechPreviewUrl;
    $('tts-preview-download').href = speechPreviewUrl;
    $('tts-preview-result').hidden = false; formError('');
  } catch (error) { if (controller === speechPreviewController) formError(error.message); }
  finally {
    if (controller === speechPreviewController) {
      speechPreviewController = null; button.disabled = state.busy; button.textContent = '生成试听（前 20 字）';
    }
  }
});
$('selection').addEventListener('change', () => { $('cloud-consent').hidden = $('selection').value !== 'ai'; $('allow-cloud').checked = false; });

async function refresh() {
  try {
    const jobs = await api('/api/jobs');
    const changed = JSON.stringify(jobs) !== JSON.stringify(state.jobs);
    state.jobs = jobs;
    if (changed || !$('jobs').dataset.loaded) renderJobs();
    $('connection-error').hidden = true;
  } catch (error) {
    $('connection-error').textContent = `无法刷新任务：${error.message}。已显示的任务会保留。`;
    $('connection-error').hidden = false;
  }
}
function renderJobs() {
  $('jobs').dataset.loaded = '1'; $('job-count').textContent = state.jobs.length;
  if (!state.jobs.length) { $('jobs').innerHTML = '<p class="job-stage">暂无制作任务</p>'; return; }
  $('jobs').innerHTML = state.jobs.map(job => `<article class="job-card">
    <div class="job-top"><h3>${esc(job.request.title)}</h3><span class="badge ${esc(job.status)}">${labels[job.status] || esc(job.status)}</span></div>
    <div class="job-meta">${esc(job.request.owner)} · ${date(job.created)} · v${job.revision}${job.parent ? ' · 修改版' : ''}</div>
    ${job.status === 'ready' ? `<img class="job-cover" src="${artifact(job,'cover.jpg')}" alt="${esc(job.request.title)}预览封面"><div class="job-summary"><strong>${Number(job.result.duration).toFixed(1)} 秒 · ${esc(job.request.ratio)}</strong>${esc(templates[job.request.template])} · ${job.result.shot_count} 个镜头<br>草稿包 ${size(job.result.package_bytes)}</div>` : `<div class="job-stage">${esc(job.error || (job.queue_position ? `前方还有 ${job.queue_position - 1} 个排队任务` : job.stage))}</div>${job.status === 'processing' ? `<progress max="100" value="${Number(job.progress)}" aria-label="制作进度 ${Number(job.progress)}%"></progress>` : ''}`}
    <div class="job-actions">${job.status === 'ready' ? `<button class="primary" data-detail="${job.id}">查看预览</button><a class="secondary" href="${artifact(job,'draft.zip')}" download>下载草稿</a>` : `<button class="secondary" data-detail="${job.id}">查看详情</button>`}
    ${['ready','needs_attention','cancelled'].includes(job.status) ? `<button class="text-button" data-revise="${job.id}">${job.status === 'ready' ? '修改一版' : '修改后重试'}</button>` : ''}
    ${['uploading','queued'].includes(job.status) ? `<button class="text-button" data-cancel="${job.id}">取消任务</button>` : ''}
    <button class="text-button" data-delete="${job.id}" ${['uploading','processing'].includes(job.status) ? 'disabled title="上传中请先取消；制作中请等待完成"' : ''}>删除任务</button></div>
  </article>`).join('');
}
async function showDetail(id) {
  try {
    const job = await api(`/api/jobs/${id}`); state.detail = id;
    $('detail-title').textContent = `${job.request.title} · v${job.revision}`;
    $('detail-content').innerHTML = `${job.status === 'ready' ? `<video class="detail-video" controls playsinline preload="metadata" poster="${artifact(job,'cover.jpg')}" src="${artifact(job,'preview.mp4')}"></video><p class="detail-note">近似预览 · 请在剪映中确认字体、动画及最终布局</p><div class="detail-actions"><a class="primary" href="${artifact(job,'draft.zip')}" download>下载剪映草稿包</a><a class="secondary" href="${artifact(job,'preview.mp4')}" download>下载近似预览</a><button class="secondary" data-revise="${job.id}">修改一版</button></div><ul class="detail-warnings">${job.result.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : `<div class="banner ${job.error ? 'error' : ''}">${esc(job.error || job.stage)}</div>`}
      <h3>视频文案</h3><div class="detail-script">${esc(job.request.script)}</div><h3>制作记录</h3><ol class="event-list">${job.events.map(event => `<li>${date(event.at)} · ${esc(event.message)}</li>`).join('') || '<li>等待上传素材</li>'}</ol>`;
    if (!$('detail-dialog').open) $('detail-dialog').showModal();
    if (job.status === 'ready' && job.result.files.includes('narration.wav')) {
      $('detail-content').insertAdjacentHTML('beforeend', `<h3>AI 口播音频</h3><audio controls preload="metadata" src="${artifact(job,'narration.wav')}"></audio><p><a class="secondary" href="${artifact(job,'narration.wav')}" download>下载口播音频</a></p>`);
    }
  } catch (error) { toast(error.message); }
}
function revise(id) {
  const job = state.jobs.find(j => j.id === id); if (!job || state.busy) return;
  state.revision = job;
  clearSpeechPreview();
  const r = job.request;
  $('narration').value = r.narration || 'none';
  $('tts-voice').value = !r.tts_speaker || r.tts_speaker === 'zh_female_vv_uranus_bigtts' ? 'zh_female_vv_uranus_bigtts' : 'custom';
  $('tts-speaker').value = r.tts_speaker || '';
  setSpeechSpeed(r.tts_speed || 1);
  updateNarration();
  for (const key of ['title','owner','script','ratio','selection']) $(key).value = r[key];
  document.querySelector(`[name=template][value="${r.template}"]`).checked = true;
  $('volume').value = Math.round(r.bgm_volume * 100); $('volume-value').textContent = $('volume').value + '%';
  $('allow-cloud').checked = false; $('cloud-consent').hidden = r.selection !== 'ai';
  $('word-count').textContent = `${r.script.length} / 3000`;
  $('media-fieldset').hidden = true; $('revision-banner').hidden = false;
  $('revision-label').textContent = `沿用 v${job.revision} 的素材，原版本保留。`;
  $('composer-title').textContent = '修改视频'; $('submit').textContent = '生成新版本 ↗';
  $('detail-dialog').close(); $('job-form').scrollIntoView({behavior: 'smooth'});
  formError('');
}
function exitRevision() {state.revision = null; $('media-fieldset').hidden = false; $('revision-banner').hidden = true; $('composer-title').textContent = '新建视频'; $('submit').textContent = '开始制作 ↗';}
$('exit-revision').addEventListener('click', exitRevision);
$('close-detail').addEventListener('click', () => $('detail-dialog').close());
$('detail-dialog').addEventListener('close', () => { $('detail-content').querySelectorAll('video,audio').forEach(el => el.pause()); state.detail = null; });
document.addEventListener('click', async e => {
  const button = e.target.closest('[data-detail],[data-revise],[data-cancel],[data-delete]'); if (!button) return;
  if (button.dataset.delete) {
    const id = button.dataset.delete, job = state.jobs.find(j => j.id === id);
    if (!job || !confirm(`删除“${job.request.title} · v${job.revision}”？\n将永久删除该任务及服务器上的素材副本、预览和草稿文件，无法恢复。排队任务不再制作，其他版本和电脑上的原始素材不受影响。`)) return;
    button.disabled = true;
    try {
      await api(`/api/jobs/${id}`, {method:'DELETE'});
      if (state.detail === id) $('detail-dialog').close();
      if (state.revision?.id === id) exitRevision();
      await refresh(); toast('任务及关联文件已删除');
    } catch (error) { toast(error.message); button.disabled = false; }
  }
  if (button.dataset.detail) showDetail(button.dataset.detail);
  if (button.dataset.revise) revise(button.dataset.revise);
  if (button.dataset.cancel) {
    button.disabled = true;
    try { await api(`/api/jobs/${button.dataset.cancel}/cancel`, {method:'POST'}); await refresh(); }
    catch (error) { toast(error.message); button.disabled = false; }
  }
});

async function uploadFile(job, file, role, completed, total) {
  const item = await api(`/api/jobs/${job.id}/files`, {method:'POST', body:JSON.stringify({name:file.name,role,size:file.size})});
  let offset = 0;
  while (offset < file.size) {
    const chunk = file.slice(offset, offset + 4 * 1024 * 1024);
    const result = await api(`/api/jobs/${job.id}/files/${item.id}?offset=${offset}`, {method:'PUT', headers:{'Content-Type':'application/octet-stream'},body:chunk});
    offset = result.received;
    const percent = Math.round((completed + offset) / total * 100);
    $('upload-bar').value = percent; $('upload-percent').textContent = `${percent}%`;
    $('upload-stage').textContent = `正在上传 ${file.name}`;
  }
  return file.size;
}
$('job-form').addEventListener('submit', async e => {
  e.preventDefault(); if (state.busy) return;
  formError('');
  if (!state.revision && (!state.videos.length || !state.music)) return formError('请至少添加一段视频和一首背景音乐。');
  const request = body();
  if (request.selection === 'ai' && !request.allow_cloud_analysis) return formError('使用 AI 选片前，请勾选关键帧分析授权。');
  const total = state.videos.reduce((n,f) => n + f.size, 0) + (state.music?.size || 0);
  if (!state.revision && total > 4 * 1024 ** 3) return formError('每个任务素材总大小最多 4GB。');
  clearSpeechPreview();
  state.busy = true; $('job-form').classList.add('busy');
  const controls = Array.from($('job-form').querySelectorAll('input,textarea,select,button'));
  const disabledBefore = controls.map(el => el.disabled);
  controls.forEach(el => el.disabled = true);
  $('submit').textContent = '正在提交…';
  let created = null;
  try {
    if (state.revision) {
      await api(`/api/jobs/${state.revision.id}/revisions`, {method:'POST', body:JSON.stringify({request})});
    } else {
      created = await api('/api/jobs', {method:'POST', body:JSON.stringify(request)});
      $('upload-progress').hidden = false; $('upload-bar').value = 0; $('upload-percent').textContent = '0%';
      let completed = 0;
      for (const file of state.videos) completed += await uploadFile(created, file, 'video', completed, total);
      await uploadFile(created, state.music, 'bgm', completed, total);
      await api(`/api/jobs/${created.id}/submit`, {method:'POST'});
    }
    savePreferences();
    toast('任务已提交，制作完成后可在右侧领取。');
    exitRevision(); state.videos = []; state.music = null; renderFiles();
    $('script').value = ''; $('title').value = ''; $('word-count').textContent = '0 / 3000';
    await refresh();
  } catch (error) {
    if (created) await api(`/api/jobs/${created.id}/cancel`, {method:'POST'}).catch(() => {});
    formError(`${error.message}。表单和所选文件已保留，可重新提交。`);
  } finally {
    state.busy = false; $('job-form').classList.remove('busy'); controls.forEach((el,i) => el.disabled = disabledBefore[i]);
    $('submit').textContent = state.revision ? '生成新版本 ↗' : '开始制作 ↗'; $('upload-progress').hidden = true;
  }
});
$('refresh').addEventListener('click', refresh);
$('login-dialog').addEventListener('cancel', e => e.preventDefault());
$('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  try {await api('/api/login', {method:'POST',body:JSON.stringify({code:$('access-code').value})}); $('access-code').value = ''; $('login-dialog').close(); await init();}
  catch (error) {$('login-error').textContent = error.message;}
});
async function init() {
  try {
    const session = await api('/api/session');
    if (!session.authenticated) { if (!$('login-dialog').open) $('login-dialog').showModal(); return; }
    state.health = await api('/api/health');
    $('machine-state').textContent = state.health.ready ? '工作机已连接' : '工作机需要配置';
    $('submit').disabled = !state.health.ready;
    $('ai-option').disabled = !state.health.ai_ready;
    $('tts-option').textContent = state.health.tts_ready ? '自动生成口播音频' : '自动生成口播音频（服务不可用时回退）';
    updateNarration();
    $('ai-option').textContent = state.health.ai_ready ? 'AI 查看画面并匹配文案' : 'AI 匹配文案（待配置）';
    if (!state.health.ready) formError('工作机缺少视频处理工具，请联系管理员。');
    await refresh();
  } catch (error) {$('machine-state').textContent = '暂未连接'; formError(error.message);}
}
const preferenceKey = 'video-workbench-preferences-v1';
function setSpeechSpeed(value) {
  const speed = String(value);
  if (![...$('tts-speed').options].some(o => o.value === speed)) $('tts-speed').add(new Option(`${speed} 倍`, speed));
  $('tts-speed').value = speed;
}
function savePreferences() {
  try {
    localStorage.setItem(preferenceKey, JSON.stringify({
      owner: $('owner').value, narration: $('narration').value,
      voice: $('tts-voice').value, speaker: $('tts-speaker').value, speed: Number($('tts-speed').value),
      ratio: $('ratio').value, selection: $('selection').value,
      template: document.querySelector('[name=template]:checked').value,
      volume: Number($('volume').value)
    }));
  } catch {}
}
function restorePreferences() {
  try {
    const cached = JSON.parse(localStorage.getItem(preferenceKey) || '{}');
    if (!cached || typeof cached !== 'object' || Array.isArray(cached)) throw new Error('Invalid preferences');
    const owner = cached.owner ?? localStorage.getItem('video-owner');
    if (typeof owner === 'string') $('owner').value = owner.slice(0,30);
    if (['none','volcengine'].includes(cached.narration)) $('narration').value = cached.narration;
    if (['zh_female_vv_uranus_bigtts','custom'].includes(cached.voice)) $('tts-voice').value = cached.voice;
    if (typeof cached.speaker === 'string') $('tts-speaker').value = cached.speaker.slice(0,120);
    if (typeof cached.speed === 'number' && Number.isFinite(cached.speed) && cached.speed >= .5 && cached.speed <= 2) {
      setSpeechSpeed(cached.speed);
    }
    if (['9:16','16:9'].includes(cached.ratio)) $('ratio').value = cached.ratio;
    if (['ordered','ai'].includes(cached.selection)) $('selection').value = cached.selection;
    if (['new','selling','promo'].includes(cached.template)) document.querySelector(`[name=template][value="${cached.template}"]`).checked = true;
    if (typeof cached.volume === 'number' && Number.isFinite(cached.volume) && cached.volume >= 0 && cached.volume <= 100) $('volume').value = cached.volume;
  } catch {}
  $('volume-value').textContent = `${$('volume').value}%`;
  $('cloud-consent').hidden = $('selection').value !== 'ai';
  updateNarration();
}
const preferenceInputs = new Set(['owner','narration','volume','tts-voice','tts-speaker','tts-speed','ratio','selection','template']);
$('job-form').addEventListener('input', e => {if (preferenceInputs.has(e.target.id || e.target.name)) savePreferences();});
restorePreferences();
init();
setInterval(() => {if (!document.hidden && !$('login-dialog').open) refresh();}, 4000);

// Optional WebMCP uses the same read and navigation actions as the visible UI.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  const tools = [{name:'list_video_jobs', title:'查看视频任务', description:'读取工作台最近的团队视频任务及真实状态。',
    inputSchema:{type:'object',properties:{},additionalProperties:false}, annotations:{readOnlyHint:true,untrustedContentHint:true},
    execute:async input => {if (!input || Object.keys(input).length) throw new Error('不接受额外参数'); await refresh(); return state.jobs.map(j => ({id:j.id,title:j.request.title,status:j.status}));}},
    {name:'open_video_job',title:'打开视频任务详情',description:'打开已有任务的详情和预览，不创建任务。',
    inputSchema:{type:'object',properties:{id:{type:'string'}},required:['id'],additionalProperties:false}, annotations:{readOnlyHint:true,untrustedContentHint:true},
    execute:async input => {if (!input || !/^[a-f0-9]{32}$/.test(input.id) || Object.keys(input).some(k => k !== 'id')) throw new Error('任务 ID 无效'); await showDetail(input.id); if (state.detail !== input.id) throw new Error('无法打开任务'); return {opened:input.id};}}];
  for (const tool of tools) Promise.resolve().then(() => document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(() => {});
  addEventListener('pagehide', () => lifecycle.abort(), {once:true});
}
