// ── State ──────────────────────────────────────────────────────────────────
let _pendingRetryBubble = null;

const state = {
  characters: [],
  selectedCharacter: null,
  selectedScenario: null,
  messages: [],          // { role, content }[]
  helperOpen: false,
  taskOpen: false,
  loading: false,
  userId: null,
  nickname: null,
  sessionId: null,
  sessionSaved: false,
};

// ── API ────────────────────────────────────────────────────────────────────
const API = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = new Error(await res.text());
      err.status = res.status;
      throw err;
    }
    return res.json();
  },
};

// ── Utilities ──────────────────────────────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(`screen-${id}`).classList.add('active');
  document.querySelector('.info-btn').style.display = id === 'landing' ? '' : 'none';
}

function showLoading(text = '思考中...') {
  document.getElementById('loading-text').textContent = text;
  document.getElementById('loading-overlay').classList.add('active');
  state.loading = true;
}

function hideLoading() {
  document.getElementById('loading-overlay').classList.remove('active');
  state.loading = false;
}

function stars(n, max = 5) {
  return '★'.repeat(n) + '☆'.repeat(max - n);
}

// Format character's message: style parenthetical actions, volume, speech marks
function formatCharMessage(text) {
  return text
    .replace(/（([^）]+)）/g, '<span class="action-text">（$1）</span>')
    .replace(/\(([^)]+)\)/g, '<span class="action-text">($1)</span>')
    .replace(/\[大聲\]/g, '<span class="volume-marker">[大聲]</span>')
    .replace(/「([^」]+)」/g, '<span class="speech-text">「$1」</span>');
}

function scrollToBottom() {
  const c = document.getElementById('messages-container');
  c.scrollTop = c.scrollHeight;
}

// ── Render Characters ──────────────────────────────────────────────────────
function renderCharacterCards() {
  const container = document.getElementById('character-cards');
  container.innerHTML = state.characters.map(char => `
    <div class="char-card" onclick="selectCharacter('${char.id}')"
         style="--card-gradient:${char.gradient};">
      <div class="char-card-avatar" style="background:${char.gradient};">
        ${char.avatar}
      </div>
      <div class="char-card-name">${char.name}</div>
      <div class="char-card-level"
           style="background:${char.color}22;color:${char.color};">
        ${char.level}
      </div>
      <p class="char-card-desc">${char.description}</p>
      <div class="char-card-traits">
        ${char.traits.slice(0, 4).map(t =>
          `<span class="trait-tag">${t}</span>`).join('')}
      </div>
    </div>
  `).join('');
}

// ── Render Scenarios ──────────────────────────────────────────────────────
function renderScenarioCards(scenarios) {
  const char = state.selectedCharacter;

  document.getElementById('selected-character-info').innerHTML = `
    <div class="selected-char-avatar" style="background:${char.gradient};">${char.avatar}</div>
    <div>
      <div class="selected-char-name">${char.name}</div>
      <div class="selected-char-level">${char.level}・${char.age}歲</div>
    </div>
  `;

  document.getElementById('scenario-cards').innerHTML = scenarios.map(s => `
    <div class="scenario-card" onclick="selectScenario('${s.id}')"
         style="--char-color:${char.color};">
      <div class="scenario-icon">${s.icon}</div>
      <div class="scenario-info">
        <div class="scenario-name">${s.name}</div>
        <div class="scenario-goal">${s.goal}</div>
        <div class="scenario-meta">
          <span class="scenario-difficulty">${stars(s.difficulty)}</span>
          <span class="scenario-role">你扮演：${s.role}</span>
        </div>
      </div>
    </div>
  `).join('');
}

// ── Chat Setup ─────────────────────────────────────────────────────────────
function setupChat() {
  const char = state.selectedCharacter;
  const scenario = state.selectedScenario;

  document.documentElement.style.setProperty('--char-color', char.color);

  document.getElementById('chat-avatar').textContent = char.avatar;
  document.getElementById('chat-avatar').style.background = char.gradient;
  document.getElementById('chat-character-name').textContent = char.name;
  document.getElementById('chat-scenario-name').textContent = scenario.name;

  document.getElementById('task-role-text').textContent = scenario.role;
  document.getElementById('task-goal-text').textContent = scenario.goal;
  document.getElementById('task-context-text').textContent = scenario.context;

  const container = document.getElementById('messages-container');
  container.innerHTML = '';

  // Welcome card (create fresh each time)
  const tips = scenario.tips
    ? scenario.tips.map(t => `<li>${t}</li>`).join('') : '';
  const welcomeEl = document.createElement('div');
  welcomeEl.className = 'message-welcome';
  welcomeEl.innerHTML = `
    <strong>📋 情境開始</strong>
    你正在扮演：<b>${scenario.role}</b><br>
    任務目標：<b>${scenario.goal}</b>
    ${tips ? `<br><br>💡 <b>溝通小提示：</b><ul style="margin:6px 0 0 16px;line-height:1.8">${tips}</ul>` : ''}
  `;
  container.appendChild(welcomeEl);

  // Character's initial message
  if (scenario.initial_message) {
    appendMessage('assistant', scenario.initial_message);
    state.messages = [{ role: 'assistant', content: scenario.initial_message }];
  } else {
    state.messages = [];
  }

  // Reset helper
  document.getElementById('helper-content').innerHTML =
    '<p class="helper-placeholder">開始對話後，點擊「取得建議」，輔導顧問會分析你的對話並給予具體建議。</p>';

  if (state.helperOpen) toggleHelper();
  document.getElementById('message-input').value = '';
}

// ── Message Rendering ──────────────────────────────────────────────────────
function appendMessage(role, content) {
  const char = state.selectedCharacter;
  const container = document.getElementById('messages-container');

  const div = document.createElement('div');
  div.className = `message ${role}`;

  const avatarEl = document.createElement('div');
  avatarEl.className = 'msg-avatar';
  if (role === 'assistant') {
    avatarEl.textContent = char.avatar;
    avatarEl.style.background = char.gradient;
  } else {
    avatarEl.textContent = '🧑';
  }

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.innerHTML = role === 'assistant'
    ? formatCharMessage(content)
    : content.replace(/\n/g, '<br>');

  div.appendChild(avatarEl);
  div.appendChild(bubble);
  container.appendChild(div);
  scrollToBottom();
}

// ── Send Message ──────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('message-input');
  const text = input.value.trim();
  if (!text || state.loading) return;

  input.value = '';
  input.style.height = 'auto';

  appendMessage('user', text);
  state.messages.push({ role: 'user', content: text });

  showLoading(`${state.selectedCharacter.name} 思考中...`);
  document.getElementById('message-input').disabled = true;
  document.querySelector('.send-btn').disabled = true;

  try {
    const data = await API.post('/api/chat', {
      character_id: state.selectedCharacter.id,
      scenario_id: state.selectedScenario.id,
      messages: state.messages,
    });

    appendMessage('assistant', data.response);
    state.messages.push({ role: 'assistant', content: data.response });
  } catch (err) {
    if (err.status === 503) {
      _pendingRetryBubble = appendRetryBubble();
    } else {
      appendMessage('assistant', '（系統錯誤：無法取得回應。請確認後端是否運行，並檢查 LLM 設定。）');
    }
    console.error(err);
  } finally {
    hideLoading();
    document.getElementById('message-input').disabled = false;
    document.querySelector('.send-btn').disabled = false;
    document.getElementById('message-input').focus();
  }
}

function appendRetryBubble() {
  const char = state.selectedCharacter;
  const container = document.getElementById('messages-container');

  const div = document.createElement('div');
  div.className = 'message assistant';

  const avatarEl = document.createElement('div');
  avatarEl.className = 'msg-avatar';
  avatarEl.textContent = char.avatar;
  avatarEl.style.background = char.gradient;

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble msg-retry-error';
  bubble.innerHTML = `<span class="retry-error-text">（伺服器暫時無法回應）</span><button class="retry-btn" onclick="retryLastMessage()">重新生成</button>`;

  div.appendChild(avatarEl);
  div.appendChild(bubble);
  container.appendChild(div);
  scrollToBottom();
  return div;
}

async function retryLastMessage() {
  if (state.loading) return;

  if (_pendingRetryBubble) {
    _pendingRetryBubble.remove();
    _pendingRetryBubble = null;
  }

  showLoading(`${state.selectedCharacter.name} 思考中...`);
  document.getElementById('message-input').disabled = true;
  document.querySelector('.send-btn').disabled = true;

  try {
    const data = await API.post('/api/chat', {
      character_id: state.selectedCharacter.id,
      scenario_id: state.selectedScenario.id,
      messages: state.messages,
    });
    appendMessage('assistant', data.response);
    state.messages.push({ role: 'assistant', content: data.response });
  } catch (err) {
    if (err.status === 503) {
      _pendingRetryBubble = appendRetryBubble();
    } else {
      appendMessage('assistant', '（系統錯誤：無法取得回應。請確認後端是否運行，並檢查 LLM 設定。）');
    }
    console.error(err);
  } finally {
    hideLoading();
    document.getElementById('message-input').disabled = false;
    document.querySelector('.send-btn').disabled = false;
    document.getElementById('message-input').focus();
  }
}


// ── Helper AI ─────────────────────────────────────────────────────────────
async function getHelperAdvice() {
  if (state.loading) return;
  if (state.messages.length === 0) {
    document.getElementById('helper-content').innerHTML =
      '<p class="helper-placeholder">先開始和對方說話，再來取得建議！</p>';
    return;
  }

  showLoading('輔導顧問分析中...');
  document.querySelector('.get-advice-btn').disabled = true;

  try {
    const data = await API.post('/api/helper', {
      character_id: state.selectedCharacter.id,
      scenario_id: state.selectedScenario.id,
      messages: state.messages,
    });
    document.getElementById('helper-content').innerHTML =
      `<div class="helper-advice">${data.advice}</div>`;
  } catch (err) {
    document.getElementById('helper-content').innerHTML =
      '<p class="helper-placeholder">取得建議時發生錯誤，請稍後再試。</p>';
    console.error(err);
  } finally {
    hideLoading();
    document.querySelector('.get-advice-btn').disabled = false;
  }
}

function toggleHelper() {
  state.helperOpen = !state.helperOpen;
  document.getElementById('helper-panel').classList.toggle('open', state.helperOpen);
  document.getElementById('helper-toggle-btn').textContent =
    state.helperOpen ? '✕ 關閉提示' : '💡 輔助提示';
}

// ── Task Accordion ────────────────────────────────────────────────────────
function toggleTask() {
  state.taskOpen = !state.taskOpen;
  document.getElementById('task-content').classList.toggle('open', state.taskOpen);
  document.getElementById('accordion-arrow').classList.toggle('open', state.taskOpen);
}

// ── Check Completion ──────────────────────────────────────────────────────
async function checkCompletion() {
  if (state.loading || state.messages.length < 2) {
    alert('請先多和對方互動再確認任務完成喔！');
    return;
  }

  showLoading('評估任務完成情況...');

  try {
    const data = await API.post('/api/check-completion', {
      character_id: state.selectedCharacter.id,
      scenario_id: state.selectedScenario.id,
      messages: state.messages,
    });
    showCompletionScreen(data);
  } catch (err) {
    hideLoading();
    console.error(err);
    alert('評估系統發生錯誤，請稍後再試。');
  }
}

function showCompletionScreen(data) {
  hideLoading();

  const char = state.selectedCharacter;
  const scenario = state.selectedScenario;
  const succeeded = data.completed === true;

  const screen = document.getElementById('screen-completion');
  screen.classList.toggle('failed', !succeeded);

  const badge = document.getElementById('completion-badge');
  badge.textContent = succeeded ? '✓ 任務成功' : '✗ 任務失敗';
  badge.className = `completion-result-badge ${succeeded ? 'success' : 'failure'}`;

  document.getElementById('completion-icon').textContent = succeeded ? '🎉' : '💪';
  document.getElementById('completion-title').textContent = succeeded ? '任務完成！' : '繼續加油！';
  document.getElementById('completion-summary').textContent =
    data.summary || (succeeded ? '你完成了這次互動體驗！' : '這次沒有達成任務目標，但每次嘗試都是學習機會！');

  const learnings = `關於${char.name}（${char.level}）的互動重點：\n` +
    char.traits.slice(0, 3).map(t => `• ${t}`).join('\n') +
    `\n\n情境「${scenario.name}」的溝通關鍵：\n` +
    (scenario.tips || []).map(t => `• ${t}`).join('\n');

  const learningEl = document.getElementById('completion-learning');
  learningEl.textContent = learnings;
  learningEl.className = `completion-learning ${succeeded ? 'success' : 'failure'}`;

  document.documentElement.style.setProperty('--char-color', char.color);

  saveSession(data.completed, data.summary);

  showScreen('completion');
}

// ── Navigation ────────────────────────────────────────────────────────────
async function selectCharacter(id) {
  const char = state.characters.find(c => c.id === id);
  if (!char) return;

  state.selectedCharacter = char;
  document.documentElement.style.setProperty('--char-color', char.color);

  showLoading('載入情境...');
  try {
    const scenarios = await API.get(`/api/characters/${id}/scenarios`);
    renderScenarioCards(scenarios);
    showScreen('scenarios');
  } catch (err) {
    alert('載入情境失敗，請重試。');
    console.error(err);
  } finally {
    hideLoading();
  }
}

async function selectScenario(id) {
  const scenarios = await API.get(
    `/api/characters/${state.selectedCharacter.id}/scenarios`
  );
  const scenario = scenarios.find(s => s.id === id);
  if (!scenario) return;

  state.selectedScenario = scenario;
  state.messages = [];
  state.helperOpen = false;
  state.taskOpen = false;
  state.sessionId = null;
  state.sessionSaved = false;

  if (state.userId) {
    try {
      const sess = await API.post('/api/sessions', {
        user_id: state.userId,
        character_id: state.selectedCharacter.id,
        scenario_id: scenario.id,
      });
      state.sessionId = sess.id;
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }

  setupChat();
  showScreen('chat');
  scrollToBottom();
}

function goBack(screen) {
  if (screen === 'landing') {
    state.selectedCharacter = null;
    state.selectedScenario = null;
    document.documentElement.style.setProperty('--char-color', '#6c63ff');
  }
  // Save incomplete session when leaving chat without completing
  if (screen === 'scenarios' && state.sessionId && !state.sessionSaved && state.messages.length > 0) {
    saveSession();
  }
  showScreen(screen);
}

function tryAgain() {
  if (!state.selectedCharacter || !state.selectedScenario) {
    showScreen('landing');
    return;
  }
  state.messages = [];
  state.helperOpen = false;
  state.taskOpen = false;
  state.sessionId = null;
  state.sessionSaved = false;
  setupChat();
  showScreen('chat');
}

// ── Nickname ───────────────────────────────────────────────────────────────
async function submitNickname() {
  const input = document.getElementById('nickname-input');
  const nick = input.value.trim();
  if (!nick) {
    input.focus();
    return;
  }

  state.nickname = nick;

  // Reuse existing userId if same nickname — no API call needed
  const savedId = localStorage.getItem('autism_uid');
  const savedNick = localStorage.getItem('autism_nick');
  if (savedId && savedNick === nick) {
    state.userId = parseInt(savedId, 10);
    showScreen('landing');
    return;
  }

  // Switch to landing immediately, register user in background
  showScreen('landing');

  try {
    const data = await API.post('/api/users', { nickname: nick });
    state.userId = data.id;
    state.nickname = data.nickname;
    localStorage.setItem('autism_uid', String(data.id));
    localStorage.setItem('autism_nick', data.nickname);
  } catch (err) {
    console.error('Failed to register user:', err);
    state.userId = null;
  }
}

// ── Session recording ──────────────────────────────────────────────────────
async function saveSession(result = null, summary = null) {
  if (!state.sessionId || state.sessionSaved) return;
  try {
    await API.post(`/api/sessions/${state.sessionId}/save`, {
      messages: state.messages,
      result,
      summary,
    });
    state.sessionSaved = true;
  } catch (err) {
    console.error('Failed to save session:', err);
  }
}

// ── Autism Info Modal ─────────────────────────────────────────────────────
function openInfo() {
  document.getElementById('info-modal-backdrop').classList.add('active');
}

function closeInfo() {
  document.getElementById('info-modal-backdrop').classList.remove('active');
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
async function init() {
  showLoading('載入中...');
  try {
    state.characters = await API.get('/api/characters');
    renderCharacterCards();
  } catch (err) {
    document.getElementById('character-cards').innerHTML =
      '<p style="color:white;opacity:0.8;text-align:center;padding:20px;">無法連線到後端伺服器。<br>請確認 FastAPI 服務已啟動。</p>';
    console.error(err);
  } finally {
    hideLoading();
  }

  // Pre-fill nickname if returning user, but always show the nickname screen first
  const savedNick = localStorage.getItem('autism_nick');
  if (savedNick) {
    document.getElementById('nickname-input').value = savedNick;
  }
  showScreen('nickname');
}

document.addEventListener('DOMContentLoaded', () => {
  init();
  document.getElementById('nickname-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitNickname();
  });
});