import { useState } from 'react';
import Downloader from './sections/Downloader.jsx';
import Library from './sections/Library.jsx';
import Settings from './sections/Settings.jsx';

export default function App() {
  const [tab, setTab] = useState('down');
  return (
    <div className="app">
      <nav className="side">
        <h1>PW Downloader</h1>
        <button className={tab === 'down' ? 'on' : ''} onClick={() => setTab('down')}>Downloader</button>
        <button className={tab === 'lib' ? 'on' : ''} onClick={() => setTab('lib')}>Library</button>
        <button className={tab === 'set' ? 'on' : ''} onClick={() => setTab('set')}>Settings</button>
      </nav>
      <div className="main">
        {tab === 'down' && <Downloader />}
        {tab === 'lib' && <Library />}
        {tab === 'set' && <Settings />}
      </div>
    </div>
  );
}
