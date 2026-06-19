/* ── Supaband WebUI — Frontend Logic ───────────────────────────── */
/* Vanilla JS, no framework, no build step, no CDN dependencies.   */

const API = '/api';
const UI = {
  // ── State ────────────────────────────────────────────────────
  currentProject: '',
  currentSession: '',
  currentSection: 'chats',
  sseSource: null,
  agentsOnline: 0,
  agentsTotal: 0,

  // ── Init ──────────────────────────────────────────────────────
  init() {
    this.loadProjects();
    this.loadSessions();
    this.loadDashboard();
    this.loadAgents();
    // Auto-refresh dashboard every 15s
    setInterval(() => this.loadDashboard(), 15000);
    setInterval(() => this.loadAgents(), 15000);
    // Enter key to send chat
    document.getElementById('chat-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
  },

  // ── API helper ────────────────────────────────────────────────
  async api(path, method = 'GET', body = null) {
    const opts = { method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(API + path, opts);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || err.error || `HTTP ${resp.status}`);
    }
    return resp.json();
  },

  // ── Section switching ─────────────────────────────────────────
  switchSection(section) {
    this.currentSection = section;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.tab[data-section="${section}"]`).classList.add('active');
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById(`section-${section}`).classList.add('active');

    // Load data for the section
    if (section === 'blackboard') this.loadBlackboard();
    else if (section === 'production') this.loadProduction();
    else if (section === 'todos') this.loadTodos();
    else if (section === 'agents') this.loadAgents();
    else if (section === 'chats') this.loadSessions();
  },

  // ── Projects ──────────────────────────────────────────────────
  async loadProjects() {
    try {
      const data = await this.api('/projects');
      const list = document.getElementById('project-list');
      const select = document.getElementById('project-select');
      list.innerHTML = '';
      select.innerHTML = '';

      if (!data.projects.length) {
        list.innerHTML = '<div class="empty-state">No projects yet</div>';
        return;
      }

      data.projects.forEach(p => {
        // Sidebar item
        const div = document.createElement('div');
        div.className = 'project-item' + (p.id === this.currentProject ? ' active' : '');
        div.innerHTML = `<div class="pname">${this.esc(p.name)}</div><div class="pdesc">${this.esc(p.description || '')}</div>`;
        div.onclick = () => this.selectProject(p.id);
        list.appendChild(div);

        // Select option
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;
        select.appendChild(opt);
      });

      if (!this.currentProject && data.projects.length) {
        this.currentProject = data.projects[0].id;
      }
      select.value = this.currentProject;
      select.onchange = () => this.selectProject(select.value);
    } catch (e) {
      console.error('loadProjects:', e);
    }
  },

  selectProject(id) {
    this.currentProject = id;
    document.getElementById('project-select').value = id;
    this.loadProjects();
    this.loadDashboard();
  },

  async newProject() {
    const name = prompt('Project name:');
    if (!name) return;
    const desc = prompt('Description (optional):', '') || '';
    try {
      await this.api('/projects', 'POST', { name, description: desc });
      this.loadProjects();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  // ── Chat Sessions ─────────────────────────────────────────────
  async loadSessions() {
    try {
      const data = await this.api('/chat/sessions');
      const list = document.getElementById('session-list');
      list.innerHTML = '';

      if (!data.sessions.length) {
        list.innerHTML = '<div class="empty-state" style="font-size:11px">No sessions</div>';
        if (!this.currentSession) this.newSession();
        return;
      }

      if (!this.currentSession) {
        this.currentSession = data.sessions[0].id;
      }

      data.sessions.forEach(s => {
        const div = document.createElement('div');
        div.className = 'session-item' + (s.id === this.currentSession ? ' active' : '');
        const count = s.msg_count || 0;
        div.innerHTML = `${this.esc(s.name)} <span style="color:var(--text-3)">(${count})</span>`;
        div.onclick = () => this.selectSession(s.id);
        list.appendChild(div);
      });

      this.loadMessages(this.currentSession);
    } catch (e) {
      console.error('loadSessions:', e);
    }
  },

  async newSession() {
    const name = prompt('Session name:', 'session ' + new Date().toLocaleTimeString());
    if (!name) return;
    try {
      const data = await this.api('/chat/session', 'POST', { name });
      this.currentSession = data.session_id;
      this.loadSessions();
      this.startSSE(data.session_id);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  selectSession(id) {
    this.currentSession = id;
    this.loadSessions();
    this.startSSE(id);
  },

  async loadMessages(sessionId) {
    if (!sessionId) return;
    try {
      const data = await this.api(`/chat/${sessionId}/messages`);
      const container = document.getElementById('chat-messages');
      container.innerHTML = '';

      if (!data.messages.length) {
        container.innerHTML = '<div class="empty-state">Send a message to start chatting with Supa</div>';
        return;
      }

      data.messages.forEach(m => {
        this.addMessage(m.role, m.content, m.timestamp);
      });
      container.scrollTop = container.scrollHeight;
    } catch (e) {
      console.error('loadMessages:', e);
    }
  },

  addMessage(role, content, timestamp) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    const time = timestamp ? new Date(timestamp).toLocaleTimeString() : '';
    div.innerHTML = `<div class="md">${this.md(content)}</div><div class="msg-meta">${time}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  },

  addUpdate(update) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `msg update ${update.type}`;
    const time = update.timestamp ? new Date(update.timestamp).toLocaleTimeString() : '';
    const typeLabel = { info: 'INFO', result: 'RESULT', warning: 'WARNING', complete: 'COMPLETE' }[update.type] || update.type;
    div.innerHTML = `<div><strong>[${typeLabel}]</strong> ${this.md(update.content)}</div><div class="msg-meta">${update.agent} — ${time}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  },

  async sendMessage() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    this.addMessage('user', msg, new Date().toISOString());

    const sendBtn = document.querySelector('.btn-send');
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';

    try {
      const data = await this.api('/chat', 'POST', {
        message: msg,
        session_id: this.currentSession,
      });
      if (data.response) {
        this.addMessage('supa', data.response, new Date().toISOString());
      }
    } catch (e) {
      this.addMessage('supa', `Error: ${e.message}`, new Date().toISOString());
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  },

  // ── SSE: Real-time task updates ───────────────────────────────
  startSSE(sessionId) {
    if (this.sseSource) {
      this.sseSource.close();
    }
    try {
      this.sseSource = new EventSource(`${API}/stream/${sessionId}`);
      this.sseSource.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);
          this.addUpdate(update);
          document.getElementById('connection-status').textContent = 'connected';
        } catch (e) {
          console.error('SSE parse error:', e);
        }
      };
      this.sseSource.onerror = () => {
        document.getElementById('connection-status').textContent = 'reconnecting...';
      };
    } catch (e) {
      console.error('SSE start failed:', e);
    }
  },

  // ── Blackboard ────────────────────────────────────────────────
  async loadBlackboard() {
    const dept = document.getElementById('bb-filter-dept').value;
    const grid = document.getElementById('blackboard-grid');
    grid.innerHTML = '<div class="loading">Loading...</div>';

    try {
      const data = await this.api(`/blackboard${dept ? '?department=' + dept : ''}`);
      grid.innerHTML = '';

      if (!data.documents.length) {
        grid.innerHTML = '<div class="empty-state">No documents on the blackboard yet. Agents will post shared documents here.</div>';
        return;
      }

      data.documents.forEach(doc => {
        const card = document.createElement('div');
        card.className = 'card';
        const pin = doc.is_pinned ? '<span class="card-pin-icon"></span>' : '';
        const deptClass = doc.department || 'research';
        card.innerHTML = `
          <div class="card-header">
            <span class="card-title">${pin}${this.esc(doc.title)}</span>
            <span class="badge ${deptClass}">${this.esc(doc.department)}</span>
          </div>
          <div class="card-body">${this.esc(doc.author)} — ${this.fmtDate(doc.updated_at)}</div>
          ${doc.tags ? `<div class="card-footer"><span>${this.esc(doc.tags)}</span></div>` : ''}
        `;
        card.onclick = () => this.showBlackboardDoc(doc.key);
        grid.appendChild(card);
      });
    } catch (e) {
      grid.innerHTML = `<div class="empty-state">Error: ${this.esc(e.message)}</div>`;
    }
  },

  async showBlackboardDoc(key) {
    try {
      const data = await this.api(`/blackboard/${key}`);
      const doc = data.doc;
      const grid = document.getElementById('blackboard-grid');
      grid.innerHTML = `
        <div class="card" style="grid-column: 1 / -1; cursor: default;">
          <div class="card-header">
            <span class="card-title">${this.esc(doc.title)}</span>
            <span class="badge ${doc.department}">${this.esc(doc.department)}</span>
          </div>
          <div class="card-body">
            <p><strong>Author:</strong> ${this.esc(doc.author)} | <strong>Updated:</strong> ${this.fmtDate(doc.updated_at)}</p>
            ${doc.tags ? `<p><strong>Tags:</strong> ${this.esc(doc.tags)}</p>` : ''}
          </div>
          <div class="prod-content md" style="margin-top:12px;">${this.md(doc.content)}</div>
          <div class="card-footer">
            <button class="btn-refresh" onclick="UI.loadBlackboard()">← Back</button>
          </div>
        </div>
      `;
    } catch (e) {
      console.error('showBlackboardDoc:', e);
    }
  },

  // ── Production ────────────────────────────────────────────────
  async loadProduction() {
    const type = document.getElementById('prod-filter-type').value;
    const grid = document.getElementById('production-grid');
    grid.innerHTML = '<div class="loading">Loading...</div>';

    try {
      let path = '/production';
      const params = [];
      if (type) params.push('item_type=' + type);
      if (this.currentProject) params.push('project_id=' + this.currentProject);
      if (params.length) path += '?' + params.join('&');

      const data = await this.api(path);
      grid.innerHTML = '';

      if (!data.items.length) {
        grid.innerHTML = '<div class="empty-state">No production items yet. Agent deliverables will appear here as postcards.</div>';
        return;
      }

      const typeIcons = {
        post: '<span class="post-icon icon-post"></span>',
        report: '<span class="post-icon icon-report"></span>',
        brief: '<span class="post-icon icon-brief"></span>',
        analysis: '<span class="post-icon icon-analysis"></span>',
        campaign: '<span class="post-icon icon-campaign"></span>',
        email: '<span class="post-icon icon-email"></span>',
        article: '<span class="post-icon icon-article"></span>',
        image: '<span class="post-icon icon-image"></span>'
      };

      data.items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'prod-card';
        const icon = typeIcons[item.item_type] || '<span class="post-icon icon-default"></span>';
        let meta = '';
        try { meta = JSON.parse(item.metadata || '{}'); } catch (e) {}
        const metaStr = Object.entries(meta).map(([k, v]) => `${k}: ${v}`).join(' | ');

        card.innerHTML = `
          <div class="card-header">
            <span class="card-title">${icon} ${this.esc(item.title)}</span>
            <span class="badge-type">${this.esc(item.item_type)}</span>
          </div>
          <div class="prod-agent">
            <div class="agent-avatar">${this.initials(item.agent_name)}</div>
            <span style="font-size:12px;color:var(--text-2)">${this.esc(item.agent_name)}</span>
          </div>
          <div class="prod-content md">${this.md(item.content)}</div>
          <div class="card-footer">
            <span>${this.fmtDate(item.created_at)}</span>
            ${metaStr ? `<span>${this.esc(metaStr)}</span>` : ''}
          </div>
        `;
        grid.appendChild(card);
      });
    } catch (e) {
      grid.innerHTML = `<div class="empty-state">Error: ${this.esc(e.message)}</div>`;
    }
  },

  // ── Todos ─────────────────────────────────────────────────────
  async loadTodos() {
    const status = document.getElementById('todo-filter-status').value;
    const list = document.getElementById('todo-list');
    list.innerHTML = '<div class="loading">Loading...</div>';

    try {
      let path = '/todos';
      const params = [];
      if (status) params.push('status=' + status);
      if (this.currentProject) params.push('project_id=' + this.currentProject);
      if (params.length) path += '?' + params.join('&');

      const data = await this.api(path);
      list.innerHTML = '';

      if (!data.todos.length) {
        list.innerHTML = '<div class="empty-state">No tasks pending approval. Agents will create approval tasks here.</div>';
        return;
      }

      data.todos.forEach(todo => {
        const div = document.createElement('div');
        div.className = `todo-item ${todo.priority} ${todo.status}`;
        const isPending = todo.status === 'pending';
        div.innerHTML = `
          <div class="todo-content">
            <div class="todo-task">${this.esc(todo.task)}</div>
            <div class="todo-meta">
              ${this.esc(todo.agent_name)} | ${todo.priority} | ${this.fmtDate(todo.created_at)}
              ${todo.resolved_at ? ` | ${todo.status} ${this.fmtDate(todo.resolved_at)}` : ''}
              ${todo.resolution_note ? ` | ${this.esc(todo.resolution_note)}` : ''}
            </div>
          </div>
          ${isPending ? `
            <div class="todo-actions">
              <button class="btn-approve" onclick="UI.approveTodo(${todo.id})">Approve</button>
              <button class="btn-reject" onclick="UI.rejectTodo(${todo.id})">Reject</button>
            </div>
          ` : ''}
        `;
        list.appendChild(div);
      });
    } catch (e) {
      list.innerHTML = `<div class="empty-state">Error: ${this.esc(e.message)}</div>`;
    }
  },

  async approveTodo(id) {
    try {
      await this.api(`/todos/${id}/approve`, 'POST', {});
      this.loadTodos();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  async rejectTodo(id) {
    const note = prompt('Reason for rejection (optional):', '') || '';
    try {
      await this.api(`/todos/${id}/reject`, 'POST', { note });
      this.loadTodos();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  // ── Agents ────────────────────────────────────────────────────
  async loadAgents() {
    const grid = document.getElementById('agent-grid');
    if (!grid) return;

    try {
      const data = await this.api('/agents');
      grid.innerHTML = '';

      const colors = {
        supa: '#4f6bed', koe: '#3b82f6', mave: '#a855f7', forge: '#06b6d4',
        quill: '#22c55e', pulse: '#f59e0b', canvas: '#ec4899',
        blobw1: '#64748b', blobw2: '#64748b', blobw3: '#64748b',
        void: '#475569'
      };

      this.agentsOnline = 0;
      this.agentsTotal = 0;

      data.agents.forEach(agent => {
        if (agent.name === 'void') return;
        this.agentsTotal++;
        if (agent.running) this.agentsOnline++;

        const color = colors[agent.name] || '#64748b';
        const health = agent.health || {};
        const cycles = health.cycles || 0;
        const msgs = health.messages_processed || 0;
        const uptime = health.uptime_seconds ? this.fmtUptime(health.uptime_seconds) : '--';

        let activityHtml = '';
        if (agent.activity && agent.activity.length) {
          activityHtml = '<div class="activity-feed">';
          agent.activity.slice(0, 5).forEach(a => {
            activityHtml += `<div class="activity-item"><span class="act-action">${this.esc(a.action)}</span> ${this.esc(a.detail || '')} <span style="float:right">${this.fmtDate(a.created_at)}</span></div>`;
          });
          activityHtml += '</div>';
        }

        const card = document.createElement('div');
        card.className = 'agent-card';
        card.innerHTML = `
          <div class="agent-header">
            <div class="agent-avatar" style="background:${color}">${this.initials(agent.name)}</div>
            <div class="agent-info">
              <div class="agent-name">${this.esc(agent.name)}</div>
              <div class="agent-role">${this.esc(agent.role)}</div>
            </div>
            <div class="status-dot ${agent.running ? 'online' : 'offline'}"></div>
          </div>
          <div class="agent-stats">
            ${agent.running ? `cycles: ${cycles} | msgs: ${msgs} | uptime: ${uptime}` : 'offline'}
          </div>
          <div class="agent-actions">
            <button class="btn-agent" onclick="UI.launchAgent('${agent.name}')">Start</button>
            <button class="btn-agent" onclick="UI.restartAgent('${agent.name}')">Restart</button>
            <button class="btn-agent danger" onclick="UI.killAgent('${agent.name}')">Stop</button>
          </div>
          ${activityHtml}
        `;
        grid.appendChild(card);
      });

      this.updateStatusBar(data.agents);
    } catch (e) {
      grid.innerHTML = `<div class="empty-state">Error: ${this.esc(e.message)}</div>`;
    }
  },

  async launchAgent(name) {
    try {
      await this.api(`/agents/${name}/launch`, 'POST');
      this.loadAgents();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  async killAgent(name) {
    try {
      await this.api(`/agents/${name}/kill`, 'POST');
      this.loadAgents();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  async restartAgent(name) {
    try {
      await this.api(`/agents/${name}/restart`, 'POST');
      setTimeout(() => this.loadAgents(), 2000);
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  },

  // ── Dashboard ─────────────────────────────────────────────────
  async loadDashboard() {
    try {
      const data = await this.api('/dashboard');
      document.getElementById('agent-status-summary').textContent =
        `${data.agents_online}/${data.agents_total} agents online`;
    } catch (e) {
      console.error('loadDashboard:', e);
    }
  },

  updateStatusBar(agents) {
    const container = document.getElementById('agent-dots');
    container.innerHTML = '';
    agents.forEach(a => {
      if (a.name === 'void') return;
      const dot = document.createElement('div');
      dot.className = 'agent-dot-item';
      dot.innerHTML = `<div class="status-dot ${a.running ? 'online' : 'offline'}"></div>${this.esc(a.name)}`;
      container.appendChild(dot);
    });
  },

  // ── Utilities ─────────────────────────────────────────────────
  esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  initials(name) {
    if (!name) return '?';
    return name.substring(0, 2).toUpperCase();
  },

  fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return iso;
    }
  },

  fmtUptime(seconds) {
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
  },

  // ── Simple Markdown Renderer ──────────────────────────────────
  md(text) {
    if (!text) return '';
    let html = this.esc(text);

    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) =>
      `<pre><code>${code.trim()}</code></pre>`);

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold and italic
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

    // Blockquotes
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // Lists (unordered)
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, (m) => '<ul>' + m + '</ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');

    // Lists (ordered)
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // Line breaks (double newline = paragraph)
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');

    // Single newlines
    html = html.replace(/\n/g, '<br>');

    // Fix: remove br inside pre
    html = html.replace(/<pre>([\s\S]*?)<\/pre>/g, (m, c) =>
      '<pre>' + c.replace(/<br>/g, '\n').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&') + '</pre>');

    return html;
  },
};

// ── Boot ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => UI.init());
