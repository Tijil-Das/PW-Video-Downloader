import { useEffect, useState } from 'react';
import { api } from '../api.js';
import DPPs from './DPPs.jsx';

const STAGE_LABEL = {
  queued: '⏳ queued', signing: '🔑 signing', downloading: '⬇ downloading',
  decrypting: '🔓 decrypting', done: '✓ saved', error: '✗ error',
};

export default function Downloader() {
  const [ext, setExt] = useState(null);
  const [srv, setSrv] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [tab, setTab] = useState('lec');

  useEffect(() => {
    api.checkExtension().then(setExt).catch(() => {});
    api.serverStatus().then(setSrv).catch(() => {});
    api.listJobs().then(setJobs).catch(() => {});
    window.__onJobStatus = (d) =>
      setJobs((prev) => {
        const i = prev.findIndex((j) => j.jobId === d.jobId);
        if (i < 0) return [...prev, { name: d.jobId, ...d }];
        const next = [...prev];
        next[i] = { ...next[i], ...d };
        return next;
      });
    const poll = setInterval(() => api.listJobs().then(setJobs).catch(() => {}), 3000);
    return () => { clearInterval(poll); window.__onJobStatus = undefined; };
  }, []);

  const toggle = async () => {
    if (srv?.running) setSrv(await api.stopServer());
    else setSrv(await api.startServer());
  };

  return (
    <div>
      <h2>Downloader</h2>
      {!ext ? <div className="card">Checking extension…</div> : !ext.installed && (
        <div className="card">
          <b>Extension not detected.</b>
          <div className="mut">Install it from:</div>
          <code>{ext.extension_path}</code>
          <div><button className="act" onClick={() => api.openFolder(ext.extension_path)}>Open folder</button></div>
        </div>
      )}
      <div className="card row">
        <span className={'dot ' + (srv?.running ? 'green' : 'red')} />
        <span>{srv?.running ? `Server running on port ${srv.port}` : 'Server stopped'}</span>
        <button className="act" onClick={toggle}>{srv?.running ? 'Stop server' : 'Start server'}</button>
      </div>
      <div className="card hint">Use <b>Ctrl+Shift+D</b> in Chrome on any PW lecture card to queue a job.</div>
      <div className="row" style={{ marginBottom: 8 }}>
        <button className={'act' + (tab === 'lec' ? ' on' : '')} onClick={() => setTab('lec')}>Lectures</button>
        <button className={'act' + (tab === 'dpp' ? ' on' : '')} onClick={() => setTab('dpp')}>DPPs</button>
      </div>
      {tab === 'dpp' ? <DPPs /> : (<>
      {jobs.length === 0 && <div className="card mut">No jobs yet.</div>}
      {jobs.map((j) => (
        <div className="card" key={j.jobId}>
          <div className="row">
            {j.thumbnailUrl && <img className="thumb" src={j.thumbnailUrl} alt="" />}
            <div style={{ flex: 1 }}>
              <div><b>{j.name || j.jobId}</b></div>
              <div className="mut">{j.detail || ''}{j.path ? ` — ${j.path}` : ''}</div>
            </div>
            <span className={'badge ' + (j.stage || '')}>{STAGE_LABEL[j.stage] || j.stage}</span>
            <span className="mut">{j.pct ?? 0}%</span>
          </div>
          <div className="bar"><div style={{ width: (j.pct ?? 0) + '%' }} /></div>
        </div>
      ))}
      </>)}
    </div>
  );
}
