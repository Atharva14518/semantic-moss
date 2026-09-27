import Link from 'next/link'

export default function LandingPage() {
  return (
    <>
      <style dangerouslySetInnerHTML={{__html: `
        .hero-section {
          display: flex;
          gap: 64px;
          align-items: center;
          margin-bottom: 100px;
        }
        .nav-container {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 24px 48px;
          border-bottom: 1px solid var(--border);
          background-color: var(--bg-surface);
        }
        .footer-container {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 32px 48px;
          border-top: 1px solid var(--border);
          background-color: var(--bg-surface);
          font-size: 13px;
          color: var(--text-muted);
        }
        .main-content {
          flex: 1;
          padding: 80px 48px;
          max-width: 1200px;
          margin: 0 auto;
          width: 100%;
        }
        .hero-title {
          font-size: 48px;
          font-weight: 700;
          line-height: 1.1;
          margin-bottom: 24px;
          letter-spacing: -1px;
        }
        @media (max-width: 900px) {
          .hero-section {
            flex-direction: column;
            align-items: flex-start;
          }
        }
        @media (max-width: 600px) {
          .nav-container, .footer-container {
            flex-direction: column;
            gap: 16px;
            align-items: flex-start;
            padding: 24px;
          }
          .main-content {
            padding: 40px 24px;
          }
          .hero-title {
            font-size: 32px;
          }
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px', fontWeight: '700', letterSpacing: '-0.3px' }}>
            <span style={{ width: '9px', height: '9px', background: 'var(--accent-primary)', borderRadius: '50%' }} />
            Recall
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '24px', fontSize: '14px' }}>
            <a href="https://github.com/Atharva14518/semantic-moss" target="_blank" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>GitHub</a>
            <a href="https://github.com/Atharva14518/semantic-moss/blob/main/BUSINESS_MODEL.md" target="_blank" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Business Model</a>
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
          {/* Hero */}
          <section className="hero-section">
            <div style={{ flex: 1 }}>
              <h1 className="hero-title">
                A shared workspace where humans and AI agents actually work together.
              </h1>
              <p style={{ fontSize: '18px', lineHeight: 1.6, color: 'var(--text-secondary)', marginBottom: '32px' }}>
                Team AI tools give you a shared workspace, or a multi-agent pipeline — never both. Recall is both at once: multiple people, multiple specialized agents, one persistent memory.
              </p>
              <Link href="/workspace" style={{
                display: 'inline-block',
                background: 'var(--accent-primary)',
                color: '#fff',
                textDecoration: 'none',
                padding: '12px 24px',
                borderRadius: 'var(--radius, 8px)',
                fontWeight: '600',
                fontSize: '15px'
              }}>
                Try Workspaces
              </Link>
            </div>
            
            <div style={{ flex: 1, width: '100%', border: '1px solid var(--border)', borderRadius: 'var(--radius, 8px)', backgroundColor: 'var(--bg-elevated)', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', boxShadow: 'var(--shadow-md, 0 4px 12px rgba(0,0,0,0.6))' }}>
              <div style={{ display: 'flex', gap: '12px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
                <div style={{ width: '30px', height: '30px', borderRadius: '50%', background: '#3a3226', border: '1px solid rgba(217,119,6,0.3)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700', flexShrink: 0 }}>U</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12.5px', fontWeight: '600', color: 'var(--accent-primary)', marginBottom: '4px' }}>Human</div>
                  <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: '0 var(--radius, 8px) var(--radius, 8px) var(--radius, 8px)', padding: '10px', fontSize: '13.5px' }}>Fix the billing webhook to handle Stripe retries.</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ width: '30px', height: '30px', borderRadius: '50%', background: '#1e2a22', border: '1px solid rgba(79,122,91,0.3)', color: 'var(--accent-agent)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700', flexShrink: 0 }}>P</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12.5px', fontWeight: '600', color: 'var(--accent-agent)', marginBottom: '4px' }}>Planner</div>
                  <div style={{ background: 'rgba(79,122,91,0.08)', borderLeft: '2px solid var(--accent-agent)', borderTopRightRadius: 'var(--radius, 8px)', borderBottomRightRadius: 'var(--radius, 8px)', borderBottomLeftRadius: 'var(--radius, 8px)', padding: '10px', fontSize: '13.5px', color: 'var(--text-primary)' }}>
                    Planned 2 subtasks:<br/>
                    1. Check Stripe docs for retry behavior<br/>
                    2. Update webhook handler code
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* How it works */}
          <section style={{ marginBottom: '100px' }}>
            <h2 style={{ fontSize: '24px', fontWeight: '600', marginBottom: '40px' }}>How it works</h2>
            <div style={{ position: 'relative', paddingLeft: '24px' }}>
              <div style={{ position: 'absolute', left: 0, top: '8px', bottom: '8px', width: '1px', background: 'var(--border)' }} />
              
              <div style={{ position: 'relative', marginBottom: '32px' }}>
                <div style={{ position: 'absolute', left: '-27.5px', top: '8px', width: '7px', height: '7px', borderRadius: '50%', background: 'var(--accent-signal)' }} />
                <p style={{ fontSize: '16px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  <strong>Ask a question about what's already happened</strong> — answered instantly from memory.
                </p>
              </div>
              
              <div style={{ position: 'relative', marginBottom: '32px' }}>
                <div style={{ position: 'absolute', left: '-27.5px', top: '8px', width: '7px', height: '7px', borderRadius: '50%', background: 'var(--accent-agent)' }} />
                <p style={{ fontSize: '16px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  <strong>Give it a real task</strong> — a Planner, an Executor, and a Reviewer agent handle it together, live.
                </p>
              </div>
              
              <div style={{ position: 'relative', marginBottom: '32px' }}>
                <div style={{ position: 'absolute', left: '-27.5px', top: '8px', width: '7px', height: '7px', borderRadius: '50%', background: 'var(--text-muted)' }} />
                <p style={{ fontSize: '16px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  <strong>Everything is visible</strong> — click "Why?" on any decision to see the actual reasoning.
                </p>
              </div>
              
              <div style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', left: '-27.5px', top: '8px', width: '7px', height: '7px', borderRadius: '50%', background: '#C4573E' }} />
                <p style={{ fontSize: '16px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                  <strong>Nothing gets stuck</strong> — if something fails repeatedly, a human gets pulled in automatically.
                </p>
              </div>
            </div>
          </section>

          {/* Proof */}
          <section>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', fontFamily: "'IBM Plex Mono', 'JetBrains Mono', monospace", borderTop: '1px solid var(--border)', paddingTop: '24px' }}>
              Built and running on Moss, LiveKit, Next.js, LangGraph, and Groq — the live workspace you're about to open runs on the same code as this page.
            </p>
          </section>
        </main>

        {/* Footer */}
        <footer className="footer-container">
          <div style={{ display: 'flex', gap: '24px' }}>
            <a href="https://github.com/Atharva14518/semantic-moss" target="_blank" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>GitHub</a>
            <a href="https://github.com/Atharva14518/semantic-moss/blob/main/BUSINESS_MODEL.md" target="_blank" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Business Model</a>
          </div>
          <div>
            Built for the Multiplayer AI and Collaborative Agents hackathon track.
          </div>
        </footer>
      </div>
    </>
  )
}
