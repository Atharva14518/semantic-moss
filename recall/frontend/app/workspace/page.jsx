import dynamic from 'next/dynamic'

const Workspace = dynamic(() => import('../src/App'), { ssr: false })

export default function Page() {
  return <Workspace />
}
