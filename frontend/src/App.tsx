import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex h-full items-center justify-center bg-neutral-950 text-neutral-100">
        <div className="text-center">
          <h1 className="text-4xl font-bold mb-2">ArchFlow</h1>
          <p className="text-neutral-400">Architecture Design & Modeling Platform</p>
        </div>
      </div>
    </QueryClientProvider>
  )
}

export default App
