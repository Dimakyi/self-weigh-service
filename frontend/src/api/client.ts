const API_BASE_URL = '/api'

export interface DashboardStats {
  total_events: number
  pending_events: number
  claimed_events: number
  retrying_events: number
  published_events: number
  dead_lettered_events: number
}

export async function testBackendConnection() {
  const response = await fetch(`${API_BASE_URL}/openapi.json`)

  if (!response.ok) {
    throw new Error('Backend connection failed')
  }

  return response.json()
}


export interface DeadLetteredEvent {
  id: string
  airline_id: number
  event_type: string
  created_at: string
  attempts: number
  last_error: string | null
  dead_lettered_at: string
}


export async function getDeadLetteredEvents(): Promise<DeadLetteredEvent[]> {
  const response = await fetch(`${API_BASE_URL}/admin/outbox/dead-lettered`)

  if (!response.ok) {
    throw new Error('Failed to fetch dead-lettered events')
  }

  return response.json()
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await fetch(
    `${API_BASE_URL}/admin/outbox/statistics`
  )

  if (!response.ok) {
    throw new Error('Failed to fetch dashboard statistics')
  }

  return response.json()
}


export default API_BASE_URL