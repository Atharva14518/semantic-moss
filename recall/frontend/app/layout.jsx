import '../src/index.css'
import '../src/App.css'

export const metadata = {
  title: 'Recall - Multiplayer AI Workspace',
  description: 'Shared workspace for humans and AI agents',
}

export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>
}
