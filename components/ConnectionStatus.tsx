'use client';

interface ConnectionStatusProps {
  backendConnected: boolean;
  wsConnected: boolean;
  botRunning: boolean;
  marketOpen: boolean;
  marketStatus: string;
}

export default function ConnectionStatus({ backendConnected, wsConnected, botRunning, marketOpen, marketStatus }: ConnectionStatusProps) {
  return (
    <div className="connection-status">
      <div className="status-item" title={`Backend: ${backendConnected ? 'Connected' : 'Disconnected'}`}>
        <span className={`status-dot ${backendConnected ? 'green' : 'red'}`} />
        <span className="status-text">Server</span>
      </div>
      <div className="status-item" title={`WebSocket: ${wsConnected ? 'Connected' : 'Disconnected'}`}>
        <span className={`status-dot ${wsConnected ? 'green' : 'red'}`} />
        <span className="status-text">WS</span>
      </div>
      <div className="status-item" title={`Bot: ${botRunning ? 'Running' : 'Stopped'}`}>
        <span className={`status-dot ${botRunning ? 'green' : 'red'}`} />
        <span className="status-text">Bot</span>
      </div>
      <div className="status-item" title={marketStatus}>
        <span className={`status-dot ${marketOpen ? 'green' : 'yellow'}`} />
        <span className="status-text">{marketOpen ? 'Open' : 'Closed'}</span>
      </div>
    </div>
  );
}
