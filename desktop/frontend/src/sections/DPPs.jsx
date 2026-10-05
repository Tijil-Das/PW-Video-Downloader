import { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function DPPs() {
  const [tree, setTree] = useState(null);
  const [open, setOpen] = useState({});
  const [prog, setProg] = useState({});

  const load = async () => {
    const t = await api.listAllChapters().catch(() => null);
    setTree(t);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const h = window.__onJobStatus;
    window.__onJobStatus = (d) => {
      if (String(d.jobId || '').startsWith('dpp-')) setProg((p) => ({ ...p, [d.jobId]: d }));
      if (h) h(d);
    };
    return () => { window.__onJobStatus = h; };
  }, []);

  if (!tree) return <div className="card">Loading chapters…</div>;
  const subjects = tree.subjects || tree || [];
  const list = Array.isArray(subjects) ? subjects : [];
  if (tree.error) return <div className="card">Error: {tree.error}</div>;
  const dlOne = async (s, c) => {
    const r = await api.downloadChapterDpps(s.subject_slug, c.chapter_slug, s.subject_name, c.chapter_name);
    if (r?.job_id) setProg((p) => ({ ...p, [r.job_id]: { detail: 'queued', pct: 0 } }));
  };
  const dlSubj = async (s) => { for (const c of (s.chapters || [])) await dlOne(s, c); };
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <button className="act" onClick={load}>Refresh chapters</button>
      </div>
      {list.map((s) => (
        <div className="card" key={s.subject_slug || s.subject_name}>
          <div className="row">
            <button className="act" onClick={() => setOpen((o) => ({ ...o, [s.subject_name]: !o[s.subject_name] }))}>
              {open[s.subject_name] ? '▾' : '▸'} {s.subject_name}
            </button>
            <button className="act" onClick={() => dlSubj(s)}>Download all subjects</button>
          </div>
          {open[s.subject_name] && (s.chapters || []).map((c) => (
            <div className="row" key={c.chapter_slug || c.chapter_name} style={{ marginTop: 6 }}>
              <span style={{ flex: 1 }}>▸ {c.chapter_name} ({c.lecture_count ?? '?'} DPPs)</span>
              <button className="act" onClick={() => dlOne(s, c)}>Download chapter</button>
            </div>
          ))}
        </div>
      ))}
      {Object.entries(prog).map(([jid, d]) => (
        <div className="card" key={jid}>
          <div className="mut">{d.detail || d.stage} — {d.pct ?? 0}%</div>
          <div className="bar"><div style={{ width: (d.pct ?? 0) + '%' }} /></div>
        </div>
      ))}
    </div>
  );
}
