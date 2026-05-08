/* ===== Utility Functions ===== */

/**
 * Format bytes to human-readable size (KB / MB).
 * @param {number} bytes
 * @returns {string}
 */
function formatSize(bytes) {
  if (bytes == null || bytes === 0) return '—';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

/**
 * Format ISO date string to local readable format.
 * @param {string|null} isoStr
 * @returns {string}
 */
function formatDate(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('zh-CN', { hour12: false });
  } catch {
    return isoStr;
  }
}

/**
 * Calculate duration in seconds between started_at and completed_at.
 * @param {string|null} startedAt
 * @param {string|null} completedAt
 * @returns {string}
 */
function formatDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return '—';
  try {
    const diff = (new Date(completedAt) - new Date(startedAt)) / 1000;
    if (diff < 0) return '—';
    return diff.toFixed(1) + 's';
  } catch {
    return '—';
  }
}
function statusBadge(status) {
  const labels = {
    pending: '待处理',
    running: '处理中',
    success: '成功',
    failed: '失败',
    skipped: '已跳过',
  };
  const label = labels[status] || status;
  return `<span class="badge badge-${status}">${label}</span>`;
}

/**
 * Simple fetch wrapper that throws on non-ok responses.
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  // 204 or no content
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

/* ===== State ===== */

/** Map of job_id -> intervalId for running-job pollers */
const _pollers = {};
/* ===== ConfigBar ===== */

async function loadConfig() {
  const container = document.getElementById('config-items');
  try {
    const cfg = await apiFetch('/api/config');
    container.innerHTML = [
      { label: '源桶', value: cfg.source_bucket },
      { label: '目标桶', value: cfg.target_bucket },
      { label: '区域', value: cfg.aws_region },
      { label: '源前缀', value: cfg.source_prefix || '（根目录）' },
      { label: '目标前缀', value: cfg.target_prefix || '（根目录）' },
    ].map(item =>
      `<div class="config-item">
        <span class="config-label">${item.label}</span>
        <span class="config-value">${escapeHtml(item.value)}</span>
      </div>`
    ).join('');

    // 用配置文件里的语言设置下拉框默认值
    if (cfg.mineru_lang) {
      const sel = document.getElementById('ocr-lang');
      if (sel) {
        // 若选项里没有该值，动态添加
        if (![...sel.options].some(o => o.value === cfg.mineru_lang)) {
          const opt = document.createElement('option');
          opt.value = cfg.mineru_lang;
          opt.textContent = cfg.mineru_lang;
          sel.appendChild(opt);
        }
        sel.value = cfg.mineru_lang;
      }
    }
  } catch (e) {
    container.innerHTML = `<span style="color:#f87171;font-size:12px;">配置加载失败: ${escapeHtml(e.message)}</span>`;
  }
}

/* ===== Tab Navigation ===== */

function switchTab(tab) {
  document.getElementById('tab-files').classList.toggle('active', tab === 'files');
  document.getElementById('tab-jobs').classList.toggle('active', tab === 'jobs');
  document.getElementById('view-files').classList.toggle('active', tab === 'files');
  document.getElementById('view-jobs').classList.toggle('active', tab === 'jobs');

  if (tab === 'files') loadFiles();
  if (tab === 'jobs') loadJobs();
}

/* ===== FileListView ===== */


async function loadFiles() {
  const loading = document.getElementById('files-loading');
  const content = document.getElementById('files-content');
  const empty = document.getElementById('files-empty');
  const errEl = document.getElementById('files-error');

  loading.style.display = 'flex';
  content.style.display = 'none';
  empty.style.display = 'none';
  errEl.innerHTML = '';

  const showAll = document.getElementById('show-all-files')?.checked || false;

  try {
    const files = await apiFetch(`/api/files?show_all=${showAll}`);
    loading.style.display = 'none';

    if (!files || files.length === 0) {
      empty.style.display = 'block';
      document.getElementById('files-content').style.display = 'block';
      document.getElementById('files-tbody').innerHTML = '';
      updateSubmitBtn();
      return;
    }

    document.getElementById('files-tbody').innerHTML = files.map(f => {
      const statusHtml = f.job_status
        ? statusBadge(f.job_status)
        : '<span style="color:#9ca3af;font-size:12px;">未提交</span>';
      return `
        <tr>
          <td><input type="checkbox" class="file-checkbox" value="${escapeAttr(f.key)}" onchange="onFileCheckChange()"></td>
          <td title="${escapeAttr(f.key)}">${escapeHtml(f.key)}</td>
          <td>${formatSize(f.size)}</td>
          <td>${statusHtml}</td>
        </tr>
      `;
    }).join('');

    content.style.display = 'block';
    updateSubmitBtn();
  } catch (e) {
    loading.style.display = 'none';
    errEl.innerHTML = `<div class="error-msg">加载文件列表失败：${escapeHtml(e.message)}</div>`;
  }
}

function toggleSelectAll(checkbox) {
  document.querySelectorAll('.file-checkbox').forEach(cb => {
    cb.checked = checkbox.checked;
  });
  updateSubmitBtn();
}

function onFileCheckChange() {
  const all = document.querySelectorAll('.file-checkbox');
  const checked = document.querySelectorAll('.file-checkbox:checked');
  document.getElementById('select-all').checked = all.length > 0 && all.length === checked.length;
  updateSubmitBtn();
}

function updateSubmitBtn() {
  const checked = document.querySelectorAll('.file-checkbox:checked');
  document.getElementById('submit-btn').disabled = checked.length === 0;
}

async function submitJobs() {
  const checked = Array.from(document.querySelectorAll('.file-checkbox:checked'));
  if (checked.length === 0) return;

  const fileKeys = checked.map(cb => cb.value);
  const lang = document.getElementById('ocr-lang')?.value || null;
  const btn = document.getElementById('submit-btn');
  const statusEl = document.getElementById('submit-status');

  btn.disabled = true;
  statusEl.textContent = '提交中…';

  try {
    const result = await apiFetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_keys: fileKeys, lang }),
    });

    statusEl.textContent = `已提交 ${result.jobs.length} 个任务`;
    // Auto-switch to job list tab
    setTimeout(() => {
      statusEl.textContent = '';
      switchTab('jobs');
    }, 800);
  } catch (e) {
    statusEl.textContent = '';
    btn.disabled = false;
    document.getElementById('files-error').innerHTML =
      `<div class="error-msg">提交失败：${escapeHtml(e.message)}</div>`;
  }
}

/* ===== JobListView ===== */

async function loadJobs() {
  const loading = document.getElementById('jobs-loading');
  const content = document.getElementById('jobs-content');
  const empty = document.getElementById('jobs-empty');
  const errEl = document.getElementById('jobs-error');

  loading.style.display = 'flex';
  content.style.display = 'none';
  empty.style.display = 'none';
  errEl.innerHTML = '';

  try {
    const jobs = await apiFetch('/api/jobs');
    loading.style.display = 'none';

    if (!jobs || jobs.length === 0) {
      empty.style.display = 'block';
      return;
    }

    renderJobsTable(jobs);
    content.style.display = 'block';

    // Start pollers for running jobs
    jobs.forEach(job => {
      if (job.status === 'running') startPoller(job.job_id);
    });
  } catch (e) {
    loading.style.display = 'none';
    errEl.innerHTML = `<div class="error-msg">加载任务列表失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderJobsTable(jobs) {
  const tbody = document.getElementById('jobs-tbody');
  tbody.innerHTML = jobs.map(job => {
    const diffBtn = job.status === 'success'
      ? `<button class="btn btn-secondary btn-sm" onclick="openDiff('${escapeAttr(job.job_id)}')">对比</button>`
      : '';
    return `
      <tr id="job-row-${escapeAttr(job.job_id)}">
        <td><input type="checkbox" class="job-checkbox" value="${escapeAttr(job.job_id)}" onchange="onJobCheckChange()"></td>
        <td title="${escapeAttr(job.file_key)}">${escapeHtml(job.file_key)}</td>
        <td>${statusBadge(job.status)}</td>
        <td>${formatDate(job.submitted_at)}</td>
        <td>${formatDate(job.completed_at)}</td>
        <td>${formatDuration(job.started_at, job.completed_at)}</td>
        <td>${formatSize(job.file_size)}</td>
        <td>${job.page_count != null ? job.page_count : '—'}</td>
        <td>${job.error ? `<span class="error-text" title="${escapeAttr(job.error)}">${escapeHtml(job.error)}</span>` : '—'}</td>
        <td>${diffBtn}</td>
      </tr>
    `;
  }).join('');
  updateJobActionBtns();
}

function updateJobRow(job) {
  const row = document.getElementById(`job-row-${job.job_id}`);
  if (!row) return;

  const diffBtn = job.status === 'success'
    ? `<button class="btn btn-secondary btn-sm" onclick="openDiff('${escapeAttr(job.job_id)}')">对比</button>`
    : '';

  // preserve checkbox state
  const wasChecked = row.querySelector('.job-checkbox')?.checked || false;

  row.innerHTML = `
    <td><input type="checkbox" class="job-checkbox" value="${escapeAttr(job.job_id)}" onchange="onJobCheckChange()" ${wasChecked ? 'checked' : ''}></td>
    <td title="${escapeAttr(job.file_key)}">${escapeHtml(job.file_key)}</td>
    <td>${statusBadge(job.status)}</td>
    <td>${formatDate(job.submitted_at)}</td>
    <td>${formatDate(job.completed_at)}</td>
    <td>${formatDuration(job.started_at, job.completed_at)}</td>
    <td>${formatSize(job.file_size)}</td>
    <td>${job.page_count != null ? job.page_count : '—'}</td>
    <td>${job.error ? `<span class="error-text" title="${escapeAttr(job.error)}">${escapeHtml(job.error)}</span>` : '—'}</td>
    <td>${diffBtn}</td>
  `;
}

/* ===== Job Batch Actions ===== */

function toggleJobsSelectAll(checkbox) {
  document.querySelectorAll('.job-checkbox').forEach(cb => { cb.checked = checkbox.checked; });
  updateJobActionBtns();
}

function onJobCheckChange() {
  const all = document.querySelectorAll('.job-checkbox');
  const checked = document.querySelectorAll('.job-checkbox:checked');
  const selectAll = document.getElementById('jobs-select-all');
  if (selectAll) selectAll.checked = all.length > 0 && all.length === checked.length;
  updateJobActionBtns();
}

function updateJobActionBtns() {
  const checked = document.querySelectorAll('.job-checkbox:checked').length;
  const deleteBtn = document.getElementById('delete-btn');
  const downloadBtn = document.getElementById('download-btn');
  if (deleteBtn) deleteBtn.disabled = checked === 0;
  if (downloadBtn) downloadBtn.disabled = checked === 0;
}

function getSelectedJobIds() {
  return Array.from(document.querySelectorAll('.job-checkbox:checked')).map(cb => cb.value);
}

async function deleteSelectedJobs() {
  const jobIds = getSelectedJobIds();
  if (jobIds.length === 0) return;
  if (!confirm(`确认删除选中的 ${jobIds.length} 条任务记录？`)) return;

  const statusEl = document.getElementById('jobs-action-status');
  statusEl.textContent = '删除中…';

  try {
    await apiFetch('/api/jobs', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: jobIds }),
    });
    statusEl.textContent = `已删除 ${jobIds.length} 条记录`;
    setTimeout(() => { statusEl.textContent = ''; }, 2000);
    loadJobs();
  } catch (e) {
    statusEl.textContent = '';
    document.getElementById('jobs-error').innerHTML =
      `<div class="error-msg">删除失败：${escapeHtml(e.message)}</div>`;
  }
}

async function downloadSelectedJobs() {
  const jobIds = getSelectedJobIds();
  if (jobIds.length === 0) return;

  const statusEl = document.getElementById('jobs-action-status');
  const btn = document.getElementById('download-btn');
  btn.disabled = true;
  statusEl.textContent = `正在打包 ${jobIds.length} 个任务，请稍候…`;

  try {
    const res = await fetch('/api/jobs/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: jobIds }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    // Trigger browser download
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const nameMatch = disposition.match(/filename="([^"]+)"/);
    const filename = nameMatch ? nameMatch[1] : 'ocr_results.zip';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    statusEl.textContent = '下载已开始';
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  } catch (e) {
    document.getElementById('jobs-error').innerHTML =
      `<div class="error-msg">打包下载失败：${escapeHtml(e.message)}</div>`;
    statusEl.textContent = '';
  } finally {
    updateJobActionBtns();
  }
}

/* ===== Job Polling ===== */

const TERMINAL_STATUSES = new Set(['success', 'failed', 'skipped']);

function startPoller(jobId) {
  if (_pollers[jobId]) return; // already polling
  _pollers[jobId] = setInterval(async () => {
    try {
      const job = await apiFetch(`/api/jobs/${jobId}`);
      updateJobRow(job);
      if (TERMINAL_STATUSES.has(job.status)) {
        stopPoller(jobId);
      }
    } catch {
      stopPoller(jobId);
    }
  }, 5000);
}

function stopPoller(jobId) {
  if (_pollers[jobId]) {
    clearInterval(_pollers[jobId]);
    delete _pollers[jobId];
  }
}

/* ===== DiffView ===== */

function openDiff(jobId) {
  location.hash = `#/diff/${jobId}`;
}

function goBack() {
  location.hash = '#/jobs';
}

async function showDiffView(jobId) {
  // Hide main view, show diff view
  document.getElementById('nav-tabs').style.display = 'none';
  document.getElementById('view-files').classList.remove('active');
  document.getElementById('view-jobs').classList.remove('active');
  document.getElementById('diff-view').classList.add('active');

  const sourcePanel = document.getElementById('source-panel');
  const resultPanel = document.getElementById('result-panel');
  const titleEl = document.getElementById('diff-title');

  sourcePanel.innerHTML = '<div class="loading" style="padding:20px"><span class="spinner"></span>加载中…</div>';
  resultPanel.innerHTML = '<div class="loading" style="padding:20px"><span class="spinner"></span>加载中…</div>';
  titleEl.textContent = '';

  // Load source URL and result in parallel
  const [sourceResult, resultResult] = await Promise.allSettled([
    apiFetch(`/api/jobs/${jobId}/source`),
    apiFetch(`/api/jobs/${jobId}/result`),
  ]);

  // Render source panel
  if (sourceResult.status === 'fulfilled') {
    const { url } = sourceResult.value;
    const isPdf = url.toLowerCase().includes('.pdf') || /\.pdf(\?|$)/i.test(url);
    if (isPdf) {
      sourcePanel.innerHTML = `<embed src="${escapeAttr(url)}" type="application/pdf" style="width:100%;height:100%;min-height:400px">`;
    } else {
      sourcePanel.innerHTML = `<img src="${escapeAttr(url)}" alt="源文件预览" style="max-width:100%;padding:12px">`;
    }
  } else {
    sourcePanel.innerHTML = `<div class="error-msg" style="margin:16px">加载源文件失败：${escapeHtml(sourceResult.reason.message)}</div>`;
  }

  // Render result panel (Markdown)
  if (resultResult.status === 'fulfilled') {
    const markdown = resultResult.value;
    const html = typeof marked !== 'undefined' ? marked.parse(markdown) : escapeHtml(markdown).replace(/\n/g, '<br>');
    resultPanel.innerHTML = `<div class="markdown-body">${html}</div>`;
  } else {
    resultPanel.innerHTML = `<div class="error-msg" style="margin:16px">加载 OCR 结果失败：${escapeHtml(resultResult.reason.message)}</div>`;
  }

  // Try to set title from job info
  try {
    const job = await apiFetch(`/api/jobs/${jobId}`);
    titleEl.textContent = job.file_key;
  } catch { /* ignore */ }
}

function hideDiffView() {
  document.getElementById('nav-tabs').style.display = '';
  document.getElementById('diff-view').classList.remove('active');
  // Stop all pollers when leaving diff view (they'll restart on loadJobs)
  Object.keys(_pollers).forEach(stopPoller);
  switchTab('jobs');
}

/* ===== File Upload ===== */

function onDragOver(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.add('dragover');
}

function onDragLeave(e) {
  document.getElementById('upload-zone').classList.remove('dragover');
}

function onDrop(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.remove('dragover');
  const files = Array.from(e.dataTransfer.files);
  if (files.length) uploadFiles(files);
}

function onFileInputChange(e) {
  const files = Array.from(e.target.files);
  if (files.length) uploadFiles(files);
  e.target.value = ''; // reset so same file can be re-selected
}

async function uploadFiles(files) {
  const statusEl = document.getElementById('upload-status');
  const errEl = document.getElementById('files-error');
  errEl.innerHTML = '';

  const total = files.length;
  let done = 0;
  let failed = 0;

  statusEl.innerHTML = `<div class="upload-progress">上传中 0 / ${total}…</div>`;

  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      await fetch('/api/upload', { method: 'POST', body: formData });
      done++;
    } catch {
      failed++;
    }
    statusEl.innerHTML = `<div class="upload-progress">上传中 ${done + failed} / ${total}…</div>`;
  }

  if (failed === 0) {
    statusEl.innerHTML = `<div class="upload-success">✓ 已上传 ${done} 个文件</div>`;
  } else {
    statusEl.innerHTML = `<div class="upload-success">✓ 成功 ${done} 个，失败 ${failed} 个</div>`;
  }
  setTimeout(() => { statusEl.innerHTML = ''; }, 3000);
  loadFiles(); // 刷新文件列表
}

/* ===== Router ===== */

function handleRoute() {
  const hash = location.hash || '';
  const diffMatch = hash.match(/^#\/diff\/(.+)$/);
  if (diffMatch) {
    showDiffView(diffMatch[1]);
  } else {
    hideDiffView();
  }
}

/* ===== HTML Escaping ===== */

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttr(str) {
  if (str == null) return '';
  return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ===== Init ===== */

window.addEventListener('hashchange', handleRoute);

document.addEventListener('DOMContentLoaded', () => {
  // 初始化 marked + KaTeX 公式渲染
  if (typeof markedKatex !== 'undefined') {
    marked.use(markedKatex({ throwOnError: false }));
  }

  loadConfig();
  handleRoute();
  // Default view: job list
  if (!location.hash || location.hash === '#/' || location.hash === '#/jobs') {
    loadJobs();
  }
});
