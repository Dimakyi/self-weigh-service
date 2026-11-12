
import './App.css'
import Sidebar from './components/Sidebar'
import { useCallback, useEffect, useState } from 'react'
import {
  testBackendConnection,
  getDeadLetteredEvents,
  getDashboardStats,
  type DashboardStats,
  type DeadLetteredEvent,
} from './api/client'

function App() {
  const [backendStatus, setBackendStatus] = useState('Checking...')
  const [deadLetteredEvents, setDeadLetteredEvents] = useState<DeadLetteredEvent[]>([])
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [isStatsLoading, setIsStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  useEffect(() => {
  const checkBackend = async () => {
    try {
      await testBackendConnection()
      setBackendStatus('Connected')
    } catch {
      setBackendStatus('Connection failed')
    }
  }

  checkBackend()

  const intervalId = setInterval(checkBackend, 10000)

  return () => {
    clearInterval(intervalId)
  }
}, [])



const fetchDashboardData = useCallback(async () => {
  try {
    const [statsData, eventsData] = await Promise.all([
      getDashboardStats(),
      getDeadLetteredEvents(),
    ])

    setStats(statsData)
    setDeadLetteredEvents(eventsData)
    setStatsError(null)
  } catch (error) {
    console.error('Failed to load dashboard data:', error)
    setStatsError('Failed to load dashboard data.')
  } finally {
    setIsStatsLoading(false)
  }
}, [])

const loadDashboardStats = useCallback(() => {
  setIsStatsLoading(true)
  setStatsError(null)
  void fetchDashboardData()
}, [fetchDashboardData])

useEffect(() => {
  void Promise.resolve().then(() => fetchDashboardData())

  const intervalId = setInterval(() => {
    void fetchDashboardData()
  }, 30000)

  return () => {
    clearInterval(intervalId)
  }
}, [fetchDashboardData])

  return (
    <div className="dashboard-layout">
      <Sidebar />

      <main className="main-content">
        <header className="dashboard-header">
          <div>
            <h1>Operations Dashboard</h1>
            <p>Monitor your Self-Weigh service operations.</p>
          </div>
        </header>

        <section className="dashboard-overview">
          <h2>Overview</h2>
          <button
            className="refresh-button"
            type="button"
            onClick={loadDashboardStats}
            disabled={isStatsLoading}
          >
            {isStatsLoading ? 'Refreshing...' : 'Refresh statistics'}
          </button>
          {isStatsLoading && <p>Loading dashboard statistics...</p>}
          {statsError && <p role="alert">{statsError}</p>}

          <div className="dashboard-cards">
            <div className="dashboard-card">
              <p>Service Health</p>
              <h3>{backendStatus}</h3>
            </div>

            <div className="dashboard-card">
              <p>Pending Events</p>
              <h3>{stats ? stats.pending_events : '--'}</h3>
            </div>

            <div className="dashboard-card">
              <p>Published Events</p>
              <h3>{stats ? stats.published_events : '--'}</h3>
            </div>

            <div className="dashboard-card">
              <p>Dead-lettered Events</p>
              <h3>{deadLetteredEvents.length}</h3>
            </div>
          </div>
        </section>
                <section className="outbox-monitoring">
          <h2>Outbox Monitoring</h2>

          <p>Monitor events that have failed delivery.</p>

          <div className="outbox-table-container">
            <table>
              <thead>
                <tr>
                  <th>Event ID</th>
                  <th>Airline ID</th>
                  <th>Event Type</th>
                  <th>Attempts</th>
                  <th>Last Error</th>
                  <th>Dead-lettered At</th>
                </tr>
              </thead>

              <tbody>
                {deadLetteredEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{event.id}</td>
                    <td>{event.airline_id}</td>
                    <td>{event.event_type}</td>
                    <td>{event.attempts}</td>
                    <td>{event.last_error ?? 'No error recorded'}</td>
                    <td>
                      {new Date(event.dead_lettered_at).toLocaleString()}
                    </td>
                  </tr>
                ))}

                {deadLetteredEvents.length === 0 && (
                  <tr>
                    <td colSpan={6}>No dead-lettered events found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
