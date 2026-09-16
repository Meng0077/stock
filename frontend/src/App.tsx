import { AppRoutes } from './app/routes'
import type { RunTransport } from './api/runTransport'
import { fakeRunTransport } from './mocks/fakeRunTransport'

interface AppProps {
  readonly runTransport?: RunTransport
}

function App({ runTransport = fakeRunTransport }: AppProps) {
  return <AppRoutes runTransport={runTransport} />
}

export default App
