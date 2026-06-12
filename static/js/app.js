const API = '/api/v1';
let token = localStorage.getItem('token') || '';
let userId = localStorage.getItem('userId') || '';
let currentSessionId = 'default';
let sessions = { 'default': [] };

// ===== Helpers =====
function toast(msg, type = 'success') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = `toast ${type} show`;
    setTimeout(() => el.classList.remove('show'), 2500);
}

async function api(path, options = {}) {
    const url = API + path;
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
        const res = await fetch(url, { ...options, headers });
        const data = await res.json();
        if (res.status === 401) { logout(); throw new Error('登录过期'); }
        return data;
    } catch (e) {
        if (e.message !== '登录过期') toast('网络错误: ' + e.message, 'error');
        throw e;
    }
}

// ===== Auth =====
function login(user, pass) {
    api('/auth/login', { method: 'POST', body: JSON.stringify({ user_id: user, password: pass }) })
        .then(d => {
            if (d.code === 200) {
                token = d.data.token; userId = d.data.user_id;
                localStorage.setItem('token', token);
                localStorage.setItem('userId', userId);
                showMain();
            } else { toast(d.msg || '登录失败', 'error'); }
        });
}

function register(user, pass) {
    api('/auth/register', { method: 'POST', body: JSON.stringify({ user_id: user, password: pass }) })
        .then(d => {
            if (d.code === 200) { toast('注册成功，请登录'); switchTab('login'); }
            else { toast(d.msg || '注册失败', 'error'); }
        });
}

function logout() {
    token = ''; userId = '';
    localStorage.removeItem('token');
    localStorage.removeItem('userId');
    showAuth();
}

// ===== Page Switching =====
function showAuth() {
    document.getElementById('auth-page').classList.add('active');
    document.getElementById('main-page').classList.remove('active');
    document.getElementById('current-user').textContent = '未登录';
}
function showMain() {
    document.getElementById('auth-page').classList.remove('active');
    document.getElementById('main-page').classList.add('active');
    document.getElementById('current-user').textContent = userId || '访客';
    loadRateStats();
}

// ===== Tab Switch =====
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.getElementById('login-form').classList.toggle('active', tab === 'login');
    document.getElementById('register-form').classList.toggle('active', tab === 'register');
}

// ===== Chat =====
function renderMessage(role, content) {
    const container = document.getElementById('chat-messages');
    const welcome = container.querySelector('.welcome-card');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `
        <div class="avatar">${role === 'user' ? '👤' : '🤖'}</div>
        <div class="bubble">${escapeHtml(content)}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function showTyping() {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.id = 'typing-indicator';
    div.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function removeTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    const sendBtn = document.getElementById('send-btn');
    input.value = '';
    input.dispatchEvent(new Event('input'));
    sendBtn.disabled = true;

    renderMessage('user', msg);
    if (!sessions[currentSessionId]) sessions[currentSessionId] = [];
    sessions[currentSessionId].push({ role: 'user', content: msg });

    showTyping();
    updateSessionInfo();

    try {
        const data = await api('/chat', {
            method: 'POST',
            body: JSON.stringify({
                message: msg,
                user_id: userId || null,
                session_id: currentSessionId,
            }),
        });
        removeTyping();
        if (data.code === 200) {
            const answer = data.data.answer || '（无回复）';
            renderMessage('assistant', answer);
            sessions[currentSessionId].push({ role: 'assistant', content: answer });
            document.getElementById('stat-intent').textContent = data.data.intent || '--';
        } else {
            renderMessage('assistant', '错误: ' + (data.msg || '未知'));
        }
    } catch {
        removeTyping();
        renderMessage('assistant', '请求失败，请检查服务状态');
    }

    sendBtn.disabled = false;
    input.focus();
    updateSessionInfo();
}

// ===== Session =====
function newSession() {
    currentSessionId = 'session_' + Date.now();
    sessions[currentSessionId] = [];
    renderSessionList();
    document.getElementById('chat-messages').innerHTML = `
        <div class="welcome-card">
            <div class="welcome-icon">🤖</div>
            <h2>欢迎使用多智能体平台</h2>
            <p>基于 LangGraph + DeepSeek 构建，支持意图识别、多轮对话、流式输出</p>
            <div class="quick-actions">
                <button class="quick-btn" data-msg="帮我写一段小红书文案">📝 写文案</button>
                <button class="quick-btn" data-msg="分析一下今天的热点话题">🔥 热点分析</button>
                <button class="quick-btn" data-msg="帮我生成一张图片的提示词">🎨 生成提示词</button>
                <button class="quick-btn" data-msg="我想了解这个平台的功能">ℹ️ 平台介绍</button>
            </div>
        </div>`;
    bindQuickActions();
    updateSessionInfo();
}

function switchSession(sid) {
    currentSessionId = sid;
    if (!sessions[sid]) sessions[sid] = [];
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    if (sessions[sid].length === 0) {
        container.innerHTML = `
            <div class="welcome-card">
                <div class="welcome-icon">🤖</div>
                <h2>欢迎使用多智能体平台</h2>
                <p>基于 LangGraph + DeepSeek 构建，支持意图识别、多轮对话、流式输出</p>
                <div class="quick-actions">
                    <button class="quick-btn" data-msg="帮我写一段小红书文案">📝 写文案</button>
                    <button class="quick-btn" data-msg="分析一下今天的热点话题">🔥 热点分析</button>
                    <button class="quick-btn" data-msg="帮我生成一张图片的提示词">🎨 生成提示词</button>
                    <button class="quick-btn" data-msg="我想了解这个平台的功能">ℹ️ 平台介绍</button>
                </div>
            </div>`;
    } else {
        sessions[sid].forEach(m => renderMessage(m.role, m.content));
    }
    bindQuickActions();
    renderSessionList();
    updateSessionInfo();
}

function clearSession() {
    api('/session/' + currentSessionId, { method: 'DELETE' }).catch(() => {});
    sessions[currentSessionId] = [];
    const container = document.getElementById('chat-messages');
    container.innerHTML = `
        <div class="welcome-card">
            <div class="welcome-icon">🤖</div>
            <h2>欢迎使用多智能体平台</h2>
            <p>基于 LangGraph + DeepSeek 构建，支持意图识别、多轮对话、流式输出</p>
            <div class="quick-actions">
                <button class="quick-btn" data-msg="帮我写一段小红书文案">📝 写文案</button>
                <button class="quick-btn" data-msg="分析一下今天的热点话题">🔥 热点分析</button>
                <button class="quick-btn" data-msg="帮我生成一张图片的提示词">🎨 生成提示词</button>
                <button class="quick-btn" data-msg="我想了解这个平台的功能">ℹ️ 平台介绍</button>
            </div>
        </div>`;
    bindQuickActions();
    updateSessionInfo();
}

function renderSessionList() {
    const list = document.getElementById('conversation-list');
    const items = Object.keys(sessions);
    if (items.length === 0) items.push('default');
    list.innerHTML = items.map(sid => {
        const active = sid === currentSessionId ? ' active' : '';
        const label = sid === 'default' ? '默认会话' : `会话 ${sid.slice(-6)}`;
        return `<div class="conv-item${active}" data-sid="${sid}">${label}</div>`;
    }).join('');
    document.querySelectorAll('.conv-item').forEach(el => {
        el.addEventListener('click', () => switchSession(el.dataset.sid));
    });
}

function updateSessionInfo() {
    document.getElementById('stat-sid').textContent = currentSessionId;
    document.getElementById('stat-msg-count').textContent = (sessions[currentSessionId] || []).length;
}

// ===== Rate Limit & Circuit Breaker =====
async function loadRateStats() {
    try {
        const data = await api('/rate-limit/stats');
        if (data.code === 200) {
            const g = data.data.global;
            const u = data.data.user;
            document.getElementById('stat-global').textContent = g ? `${g.tokens}/${g.capacity}` : '--';
            document.getElementById('stat-user').textContent = u ? `${u.tokens}/${u.capacity}` : '--';

            const dot = document.querySelector('.rate-dot');
            if (g && g.tokens <= g.capacity * 0.2) { dot.className = 'rate-dot danger'; }
            else if (g && g.tokens <= g.capacity * 0.5) { dot.className = 'rate-dot warning'; }
            else { dot.className = 'rate-dot'; }

            // Circuit breaker status
            const pool = data.data.llm_pool;
            if (pool && pool.length > 0) {
                const poolStat = document.getElementById('stat-pool');
                const alive = pool.filter(k => k.state === 'closed').length;
                const degraded = pool.filter(k => k.state !== 'closed').length;
                let html = '';
                if (degraded === 0) html = `<span style="color:var(--success)">${alive}/${pool.length} 正常</span>`;
                else if (alive === 0) html = `<span style="color:var(--danger)">${degraded} 熔断</span>`;
                else html = `<span style="color:var(--warning)">${alive}正常 ${degraded}熔断</span>`;
                poolStat.innerHTML = html;
            }
        }
    } catch {}
}

// ===== MCP Tools =====
async function loadMCPTools() {
    try {
        const data = await api('/mcp/tools');
        if (data.code === 200 && data.data.length > 0) {
            const html = data.data.map(t => `<div class="stat-item"><span class="stat-label">${t.name}</span><span class="stat-value" style="font-size:11px;color:var(--text-secondary)">${t.description.slice(0,20)}...</span></div>`).join('');
            document.getElementById('mcp-tools').innerHTML = html;
        }
    } catch {}
}

// ===== Quick Actions =====
function bindQuickActions() {
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const msg = btn.dataset.msg;
            document.getElementById('chat-input').value = msg;
            document.getElementById('chat-input').dispatchEvent(new Event('input'));
            sendMessage();
        });
    });
}

// ===== Sidebar Toggle =====
document.getElementById('sidebar-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
});

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    // Auth
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.addEventListener('click', () => switchTab(b.dataset.tab));
    });
    document.getElementById('login-form').addEventListener('submit', e => {
        e.preventDefault();
        login(document.getElementById('login-user').value, document.getElementById('login-pass').value);
    });
    document.getElementById('register-form').addEventListener('submit', e => {
        e.preventDefault();
        register(document.getElementById('reg-user').value, document.getElementById('reg-pass').value);
    });
    document.getElementById('guest-btn').addEventListener('click', () => showMain());
    document.getElementById('logout-btn').addEventListener('click', () => logout());

    // Chat
    document.getElementById('send-btn').addEventListener('click', sendMessage);
    const input = document.getElementById('chat-input');
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    input.addEventListener('input', () => {
        document.getElementById('char-count').textContent = `${input.value.length} / 4096`;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Quick actions
    bindQuickActions();

    // Sidebar
    document.getElementById('new-chat-btn').addEventListener('click', newSession);
    document.getElementById('clear-chat-btn').addEventListener('click', clearSession);

    // Rate limit
    document.getElementById('refresh-rate-btn').addEventListener('click', loadRateStats);
    setInterval(loadRateStats, 30000);

    // MCP tools
    loadMCPTools();
    setInterval(loadMCPTools, 60000);

    // Session init
    renderSessionList();
    updateSessionInfo();

    // Auto-login if token exists
    if (token) {
        api('/health').then(d => {
            if (d.code === 200) showMain();
            else { logout(); }
        }).catch(() => logout());
    }
});
