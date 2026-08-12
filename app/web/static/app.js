// 企业微信群发系统 — 前端交互

let autoRefreshTimer = null;

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
  updateConnectionStatus();
  startAutoRefresh();
});

// ===== 连接状态 =====
function updateConnectionStatus() {
  const statusEl = document.getElementById('connection-status');
  if (statusEl) {
    statusEl.className = 'status online';
    statusEl.textContent = '● 已连接';
  }
}

// ===== 自动刷新 =====
function startAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  autoRefreshTimer = setInterval(refreshData, 30000); // 每30秒刷新
}

function refreshData() {
  fetch('/api/dashboard')
    .then(r => r.json())
    .then(data => {
      updateDashboard(data);
    })
    .catch(err => console.error('刷新失败:', err));
}

// ===== 更新仪表盘 =====
function updateDashboard(data) {
  // 统计卡片
  setValue('online-count', data.online_workers);
  setValue('total-workers', data.total_workers);
  setValue('active-groups', data.active_groups_count);
  setValue('alert-count', data.alerts_count);
  setValue('send-completed', data.send_tasks.completed);
  setValue('send-failed', data.send_tasks.failed);

  // 更新时间
  const updateEl = document.getElementById('last-update');
  if (updateEl) {
    updateEl.textContent = '更新于 ' + new Date().toLocaleTimeString();
  }

  // 执行端列表
  const workerList = document.getElementById('worker-list');
  if (workerList && data.worker_list) {
    workerList.innerHTML = data.worker_list.map(w => `
      <tr>
        <td>
          <span class="status-dot ${w.status === 'online' ? 'online' : 'offline'}"></span>
          ${w.status === 'online' ? '在线' : '离线'}
        </td>
        <td>${w.name}</td>
        <td>${w.group_count}</td>
        <td>${w.last_heartbeat || '-'}</td>
        <td>${(w.monitor_stats && w.monitor_stats.assigned_groups) || '-'}</td>
      </tr>
    `).join('') || '<tr><td colspan="5" class="text-center text-muted">暂无执行端</td></tr>';
  }

  // 预警徽章
  const badge = document.getElementById('alert-badge');
  if (badge) {
    if (data.alerts_count > 0) {
      badge.style.display = 'inline';
      badge.textContent = data.alerts_count;
    } else {
      badge.style.display = 'none';
    }
  }
}

function setValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

// ===== 立即群发 =====
function triggerSend() {
  if (!confirm('确认立即向今日活跃群发送消息？')) return;

  fetch('/api/send/trigger', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        alert(`群发任务已下发！\n活跃群: ${data.active_groups}\n任务数: ${data.tasks_dispatched}`);
        refreshData();
      } else {
        alert('下发失败');
      }
    })
    .catch(err => alert('请求失败: ' + err));
}

// ===== 确认预警 =====
function acknowledgeAlert(groupName) {
  fetch('/api/alerts/acknowledge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_name: groupName })
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) refreshData();
    });
}

// ===== 群管理 =====
function importGroups() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv,.txt';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const lines = ev.target.result.split('\n').map(l => l.trim()).filter(Boolean);
      // 按第一行导入群名
      const groupNames = lines.map(l => l.split(',')[0].trim()).filter(Boolean);
      alert(`识别到 ${groupNames.length} 个群\n(完整导入功能待实现)`);
    };
    reader.readAsText(file);
  };
  input.click();
}

function exportGroups() {
  alert('导出功能待实现');
}

// ===== 模板 =====
function loadTemplate() {
  const select = document.getElementById('template-select');
  // 待实现：加载模板列表
}

function saveTemplate() {
  const content = document.getElementById('template-editor')?.value;
  if (!content) return;
  // 待实现：保存模板
  alert('保存功能待实现');
}

function previewTemplate() {
  const content = document.getElementById('template-editor')?.value;
  const preview = document.getElementById('preview-content');
  if (preview) {
    preview.textContent = content || '(暂无内容)';
  }
}
