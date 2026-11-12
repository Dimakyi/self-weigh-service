import './Sidebar.css'

function Sidebar() {
  return (
    <aside className="sidebar">
      <h2 className="sidebar-title">Self-Weigh</h2>

      <nav className="sidebar-nav">
        <p>Overview</p>
        <p>System Health</p>
        <p>Outbox Monitoring</p>
      </nav>
    </aside>
  )
}

export default Sidebar