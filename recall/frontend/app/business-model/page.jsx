import Link from 'next/link'

export default function BusinessModelPage() {
  return (
    <>
      <style dangerouslySetInnerHTML={{__html: `
        .nav-container {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 24px 48px;
          border-bottom: 1px solid var(--border);
          background-color: var(--bg-surface);
        }
        .main-content {
          flex: 1;
          padding: 80px 48px;
          max-width: 800px;
          margin: 0 auto;
          width: 100%;
        }
        h1 { font-size: 36px; font-weight: 700; margin-bottom: 16px; letter-spacing: -0.5px; }
        h2 { font-size: 20px; font-weight: 600; margin-top: 48px; margin-bottom: 16px; color: var(--text-primary); }
        p { font-size: 16px; line-height: 1.6; color: var(--text-secondary); margin-bottom: 16px; }
        .intro-text { font-size: 18px; font-weight: 500; color: var(--accent-primary); margin-bottom: 48px; display: inline-block; }
        @media (max-width: 600px) {
          .nav-container { flex-direction: column; gap: 16px; align-items: flex-start; padding: 24px; }
          .main-content { padding: 40px 24px; }
          h1 { font-size: 28px; }
        }
      `}} />
      <div style={{
        minHeight: '100vh',
        backgroundColor: 'var(--bg-base)',
        color: 'var(--text-primary)',
        display: 'flex',
        flexDirection: 'column'
      }}>
        {/* Nav */}
        <nav className="nav-container">
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px', fontWeight: '700', letterSpacing: '-0.3px', textDecoration: 'none', color: 'var(--text-primary)' }}>
            <span style={{ width: '9px', height: '9px', background: 'var(--accent-primary)', borderRadius: '50%' }} />
            Recall
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: '24px', fontSize: '14px' }}>
            <Link href="/" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Home</Link>
            <a href="https://github.com/Atharva14518/semantic-moss" target="_blank" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>GitHub</a>
            <Link href="/workspace" style={{
              background: 'var(--accent-primary)',
              color: '#fff',
              textDecoration: 'none',
              padding: '8px 16px',
              borderRadius: 'var(--radius, 8px)',
              fontWeight: '600',
              fontSize: '13px'
            }}>
              Try Workspaces
            </Link>
          </div>
        </nav>

        <main className="main-content">
          <h1>Business Model</h1>
          <span className="intro-text">Recall is priced and sold like workplace software, not like an AI API.</span>
          
          <h2>Who pays</h2>
          <p>Teams and organizations that already have people collaborating with AI agents on real work — the same buyer who pays for Slack, Notion, or Linear today. Not individual developers paying per API call.</p>
          
          <h2>How it's priced</h2>
          <p>Per workspace (or per seat within a workspace), the same way team software is normally sold — not per question asked, not per token used. A team pays a flat monthly amount to run persistent, shared workspaces where their people and their AI agents work together.</p>
          
          <h2>Why this pricing model, not usage-based</h2>
          <p>Charging per AI call puts Recall in direct competition with the model providers themselves and every other thin wrapper around the same model — a race to the bottom on price. Pricing the workspace itself, the way Slack or Notion do, means what's actually being sold is the accumulated shared context: the task history, the decisions, the reasoning trail an agent team builds up over weeks and months. That's not a commodity, and it can't be replicated by a competitor switching to a cheaper model.</p>
          
          <h2>Why it's defensible</h2>
          <p>A workspace's value grows the longer a team stays, because the memory it holds — every past decision, every "why" behind an agent's action — becomes harder to walk away from the more of it accumulates. That's the same retention mechanic that makes tools like Notion or Linear sticky: not feature lock-in, history lock-in.</p>
          
          <h2>Who the first customers actually are</h2>
          <p>Small, distributed teams already using multiple AI agents for real work, feeling this exact pain today — no shared context between teammates, no visibility into why an agent did something, no safe way to let an agent act autonomously with a human able to step in when needed. That's a current, real problem for any team adopting agentic AI right now, not a hypothetical one.</p>
          
          <h2>The moat</h2>
          <p>Most AI products compete on which model they wrap. Recall doesn't compete there — it sits on top of whichever model a team already trusts, and its value is the shared workspace layer itself, not the intelligence underneath it. A competitor can copy a feature. They can't retroactively copy a team's accumulated shared history.</p>
        </main>
      </div>
    </>
  )
}
