import { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function Settings() {
  const [cfg, setCfg] = useState(null);
  const [msg, setMsg] = useState('');

  useEffect(() => { api.getSettings().then(setCfg).catch(() => {}); }, []);

  const save = async () => {
    const out = await api.saveSettings({ ws_port: cfg.ws_port, auto_start_server: cfg.auto_start_server });
    setCfg(out);
    setMsg('Saved.');
    setTimeout(() => setMsg(''), 2000);
  };

  if (!cfg) return <div className="card">Loading…</div>;
  const det = cfg.detection || {};
  return (
    <div>
      <h2>Settings</h2>
      <div className="card">
        <label className="tog">
          <input type="checkbox" checked={!!cfg.auto_start_server}
            onChange={(e) => setCfg({ ...cfg, auto_start_server: e.target.checked })} />
          Auto-start server on app launch
        </label>
        <div className="row">
          <span>WebSocket port</span>
          <input type="number" value={cfg.ws_port}
            onChange={(e) => setCfg({ ...cfg, ws_port: Number(e.target.value) })} />
        </div>
        <div style={{ marginTop: 8 }}>
          <button className="act" onClick={save}>Save</button>
          <button className="act" style={{ marginLeft: 8 }}
            onClick={async () => { const s = await api.serverStatus(); setMsg(s.running ? `Server UP on ${s.port}` : 'Server DOWN'); }}>
            Test connection
          </button>
          <span className="mut" style={{ marginLeft: 8 }}>{msg}</span>
        </div>
      </div>
      <div className="card">
        <div>Extension folder (read-only):</div>
        <code>{cfg.extension_path}</code>
        <div style={{ marginTop: 6 }}>
          <button className="act" onClick={() => api.openFolder(cfg.extension_path)}>Open folder</button>
        </div>
      </div>
      <div className="card">
        <div>Chrome detection: <b>{det.installed ? 'installed' : 'not found'}</b></div>
        <div className="mut">Profiles: {(det.profiles || []).join(', ') || '—'}</div>
        <div className="mut">Method: {det.detection_method || '—'} · ID: {det.extension_id || '—'}</div>
      </div>
    </div>
  );
}
