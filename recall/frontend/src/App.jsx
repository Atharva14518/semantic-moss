import { useState, useEffect, useRef, useCallback } from 'react'
import './index.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8100'
const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8100'

// ── Utilities ─────────────────────────────────────────────────────

const WORKSPACE_ID = (() => {
  const stored = localStorage.getItem('recall_ws_id')
  if (stored) return stored
  const id = '00000000-0000-0000-0000-' + Math.random().toString(16).slice(2).padEnd(12, '0').slice(0, 12)
  localStorage.setItem('recall_ws_id', id)
  return id
})()

const CLIENT_ID = Math.random().toString(36).slice(2, 8)
const DISPLAY_NAME = localStorage.getItem('recall_display_name') || 'You'

function fmtTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function avatarInitial(role) {
  const map = { planner: 'P', executor: 'E', reviewer: 'R', system: '⚙', human: DISPLAY_NAME[0].toUpperCase() }
  return map[role] || role[0].toUpperCase()
}

function statusClass(status) {
  return `task-status-badge status-${status}`
}

function subtaskDot(status) {
  if (status === 'completed') return 'subtask-dot dot-completed'
  if (status === 'failed') return 'subtask-dot dot-failed'
  return 'subtask-dot dot-pending'
}

// ── Components ────────────────────────────────────────────────────

function PresenceDot({ type }) {
  return <span className={`presence-dot ${type}`} />
}

function Sidebar({ participants, wsId, allowedDomains }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <span className="logo-dot" />
          Recall
        </div>
        <div className="sidebar-ws-name">Workspace</div>
        <div className="ws-id-pill" title={wsId}>{wsId.slice(-8)}</div>
      </div>
      {allowedDomains?.length > 0 && (
        <>
          <div className="sidebar-section-label">Allowlist</div>
          <ul className="allowlist">
            {allowedDomains.map(d => (
              <li key={d} className="allowlist-item">{d}</li>
            ))}
          </ul>
        </>
      )}

      <div className="sidebar-section-label">Participants</div>
      <ul className="participant-list">
        {participants.map(p => (
          <li key={p.id} className="participant-item">
            <PresenceDot type={p.type} />
            <span className="participant-name">{p.name}</span>
            <span className="participant-role">{p.role}</span>
          </li>
        ))}
      </ul>
    </aside>
  )
}

function MessageRow({ msg }) {
  const isAgent = ['planner', 'executor', 'reviewer'].includes(msg.role)
  const isFlagged = msg.flagged || msg.type === 'flagged_event' || msg.event_type === 'domain_blocked'
  const isEscalated = !isFlagged && (msg.content?.includes('escalated') || msg.content?.includes('⚠'))
  const isDone = msg.content?.startsWith('✓')

  let contentClass = 'message-content'
  if (isAgent && !isFlagged) contentClass += ' agent-content'
  if (isEscalated) contentClass += ' escalated'
  if (isDone) contentClass += ' completed'
  if (isFlagged) contentClass += ' flagged'

  return (
    <div className={`message-row ${isFlagged ? 'message-row-flagged' : ''}`}>
      <div className={`message-avatar ${isFlagged ? 'avatar-flagged' : `avatar-${msg.role || 'system'}`}`}>
        {isFlagged ? '!' : avatarInitial(msg.role || 'system')}
      </div>
      <div className="message-body">
        <div className="message-meta">
          <span className={`message-author ${isFlagged ? 'flagged' : isAgent ? 'agent' : msg.role === 'human' ? 'human' : 'system'}`}>
            {isFlagged ? 'Executor' : (msg.role ? msg.role.charAt(0).toUpperCase() + msg.role.slice(1) : 'System')}
            {msg.display_name && msg.role === 'human' ? ` — ${msg.display_name}` : ''}
          </span>
          {isFlagged && <span className="flagged-badge">Flagged</span>}
          <span className="message-time">{fmtTime(msg.timestamp || msg.created_at)}</span>
        </div>
        <div className={contentClass}>{msg.content}</div>
        {isFlagged && msg.hostname && (
          <div className="flagged-detail">blocked host {msg.hostname}</div>
        )}
      </div>
    </div>
  )
}

function TaskCard({ task, active, onClick }) {
  return (
    <div className={`task-card ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="task-card-goal">{task.goal}</div>
      <div className="task-card-meta">
        <span className={statusClass(task.status)}>{task.status}</span>
      </div>
      {task.subtasks && task.subtasks.length > 0 && (
        <div className="subtask-list">
          {task.subtasks.slice(0, 4).map(s => (
            <div key={s.id} className="subtask-item">
              <span className={subtaskDot(s.status)} />
              <span>{s.description}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TaskPane({ tasks, activeTaskId, onTaskClick }) {
  return (
    <aside className="task-pane">
      <div className="task-pane-header">
        <div className="task-pane-title">📋 Task Board</div>
      </div>
      <div className="task-pane-body">
        {tasks.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🤖</div>
            <div className="empty-state-text">No tasks yet.<br />Submit a goal to start.</div>
          </div>
        ) : (
          tasks.map(t => (
            <TaskCard
              key={t.task_id}
              task={t}
              active={t.task_id === activeTaskId}
              onClick={() => onTaskClick(t)}
            />
          ))
        )}
      </div>
    </aside>
  )
}

// ── Main App ──────────────────────────────────────────────────────

const AGENTS = [
  { id: 'planner',  name: 'Planner',  role: 'Agent', type: 'agent' },
  { id: 'executor', name: 'Executor', role: 'Agent', type: 'agent' },
  { id: 'reviewer', name: 'Reviewer', role: 'Agent', type: 'agent' },
]

export default function App() {
  const [messages, setMessages] = useState([])
  const [tasks, setTasks] = useState([])
  const [activeTaskId, setActiveTaskId] = useState(null)
  const [goal, setGoal] = useState('')
  const [sending, setSending] = useState(false)
  const [connected, setConnected] = useState(false)
  const [clients, setClients] = useState(1)
  const [allowedDomains, setAllowedDomains] = useState([])

  const wsRef = useRef(null)
  const threadRef = useRef(null)
  const pollRef = useRef(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages])

  // WebSocket connection
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(`${WS_BASE}/ws/${WORKSPACE_ID}?client_id=${CLIENT_ID}`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        // keep-alive ping every 30s
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
        }, 30000)
        ws._pingInterval = ping
      }

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data)
        if (data.type === 'pong') return
        if (data.type === 'presence') {
          setClients(data.clients)
          return
        }
        if (data.type === 'flagged_event') {
          setMessages(prev => {
            if (prev.some(m => m.id === data.id || m.audit_id === data.audit_id)) return prev
            return [...prev, { ...data, timestamp: data.created_at || new Date().toISOString() }]
          })
        }
        if (data.type === 'agent_message') {
          setMessages(prev => [...prev, { ...data, timestamp: data.created_at || new Date().toISOString() }])
        }
        if (data.type === 'human_message') {
          setMessages(prev => [...prev, { ...data, role: 'human', timestamp: data.timestamp || new Date().toISOString() }])
        }
      }

      ws.onclose = () => {
        setConnected(false)
        clearInterval(ws._pingInterval)
        // Reconnect after 3s
        setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()
    return () => wsRef.current?.close()
  }, [])

  // Poll active task for updates
  const pollTask = useCallback(async (taskId) => {
    try {
      const r = await fetch(`${API}/workspace/${WORKSPACE_ID}/task/${taskId}`)
      const t = await r.json()
      setTasks(prev => prev.map(x => x.task_id === taskId ? { ...x, ...t } : x))
      if (['completed', 'escalated', 'failed'].includes(t.status)) {
        clearInterval(pollRef.current)
      }
    } catch (_) {}
  }, [])

  // Fetch task list, workspace isolation, and prior flagged events
  useEffect(() => {
    const load = async () => {
      try {
        const [tasksRes, wsRes, auditRes] = await Promise.all([
          fetch(`${API}/workspace/${WORKSPACE_ID}/tasks`),
          fetch(`${API}/workspace/${WORKSPACE_ID}`),
          fetch(`${API}/workspace/${WORKSPACE_ID}/audit`),
        ])
        const list = await tasksRes.json()
        setTasks(list)
        if (list.length > 0) setActiveTaskId(list[0].task_id)
        const ws = await wsRes.json()
        if (ws.allowed_domains) setAllowedDomains(ws.allowed_domains)
        const audit = await auditRes.json()
        if (Array.isArray(audit)) {
          const flagged = audit
            .filter(a => a.event_type === 'domain_blocked')
            .slice()
            .reverse()
            .map(a => ({
              id: a.id,
              audit_id: a.id,
              type: 'flagged_event',
              flagged: true,
              event_type: a.event_type,
              role: 'executor',
              content: a.payload?.error
                ? `Blocked navigation to ${a.payload.url || ''}. ${a.payload.error}`
                : `Blocked navigation to ${a.payload?.url || 'unknown URL'}`,
              hostname: a.payload?.hostname,
              url: a.payload?.url,
              created_at: a.created_at,
              timestamp: a.created_at,
            }))
          setMessages(prev => (prev.length ? prev : flagged))
        }
      } catch (_) {}
    }
    load()
  }, [])

  const handleSend = async () => {
    if (!goal.trim() || sending) return
    setSending(true)

    // Optimistically show human message in thread
    const humanMsg = {
      id: Math.random().toString(36).slice(2),
      role: 'human',
      display_name: DISPLAY_NAME,
      content: goal,
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, humanMsg])

    // Broadcast to other WS clients
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'human_message', content: goal, display_name: DISPLAY_NAME }))
    }

    try {
      const r = await fetch(`${API}/workspace/${WORKSPACE_ID}/task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, display_name: DISPLAY_NAME }),
      })
      const task = await r.json()
      setTasks(prev => [task, ...prev])
      setActiveTaskId(task.task_id)
      setGoal('')

      // Poll every 3s until done
      clearInterval(pollRef.current)
      pollRef.current = setInterval(() => pollTask(task.task_id), 3000)

    } catch (e) {
      console.error(e)
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend()
  }

  const participants = [
    { id: 'you', name: DISPLAY_NAME, role: 'Human', type: 'online' },
    ...AGENTS,
    ...(clients > 1 ? [{ id: 'other', name: `+${clients - 1} more`, role: '', type: 'online' }] : []),
  ]

  return (
    <div className="app-shell">
      <Sidebar participants={participants} wsId={WORKSPACE_ID} allowedDomains={allowedDomains} />

      {/* ── Center Thread ── */}
      <div className="center-pane">
        <div className="thread-header">
          <div>
            <div className="thread-title">Activity Thread</div>
            <div className="thread-subtitle">Workspace · {clients} connected</div>
          </div>
          {connected && (
            <div className="live-badge">
              <span className="live-badge-dot" />
              LIVE
            </div>
          )}
        </div>

        <div className="thread-body" ref={threadRef}>
          {messages.length === 0 && (
            <div className="empty-state" style={{ margin: 'auto' }}>
              <div className="empty-state-icon">✨</div>
              <div className="empty-state-text">
                Submit a goal below to start.<br />
                Agents will collaborate in real-time.
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageRow key={msg.id || i} msg={msg} />
          ))}
          {sending && (
            <div className="message-row" style={{ opacity: 0.5 }}>
              <div className="message-avatar avatar-planner">P</div>
              <div className="message-body">
                <div className="message-meta">
                  <span className="message-author agent">Planner</span>
                  <span className="message-time">thinking...</span>
                </div>
                <div className="message-content agent-content">
                  <span className="spinner" />
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="thread-input-area">
          <div className="input-row">
            <textarea
              className="goal-input"
              placeholder="Describe a goal for the agents… (⌘↵ to send)"
              value={goal}
              onChange={e => setGoal(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
            />
            <button className="send-btn" onClick={handleSend} disabled={sending || !goal.trim()}>
              {sending ? <span className="spinner" /> : 'Run →'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Right Task Pane ── */}
      <TaskPane
        tasks={tasks}
        activeTaskId={activeTaskId}
        onTaskClick={t => setActiveTaskId(t.task_id)}
      />
    </div>
  )
}
