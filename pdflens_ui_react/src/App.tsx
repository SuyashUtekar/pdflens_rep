import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { getConfigurations, getHealth, retrieveZip, submitPdf } from './api';
import type { ConfigOption, ExtractionOptions, JobRecord } from './types';

const HISTORY_KEY = 'pdflens.react.history.v1';
const defaultOptions: ExtractionOptions = {
  extract_tables: true,
  extract_images: true,
  extract_header: true,
  extract_footer: true,
  extract_hyperlinks: true,
  extract_footnotes: false,
};

const optionLabels: { key: keyof ExtractionOptions; title: string; note: string }[] = [
  { key: 'extract_tables', title: 'Tables', note: 'Detect and extract tables' },
  { key: 'extract_images', title: 'Images', note: 'Extract image assets' },
  { key: 'extract_header', title: 'Headers', note: 'Capture page headers' },
  { key: 'extract_footer', title: 'Footers', note: 'Capture page footers' },
  { key: 'extract_hyperlinks', title: 'Hyperlinks', note: 'Preserve detected links' },
  { key: 'extract_footnotes', title: 'Footnotes', note: 'Capture footnotes' },
];

function loadHistory(): JobRecord[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((row): row is JobRecord =>
      typeof row === 'object' && row !== null &&
      typeof row.request_id === 'string' && typeof row.filename === 'string' &&
      typeof row.status === 'string' && typeof row.submitted_at === 'string',
    ).slice(0, 100);
  } catch {
    return [];
  }
}

function saveHistory(rows: JobRecord[]): boolean {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(rows.slice(0, 100)));
    return true;
  } catch {
    // The current page session continues to work if browser storage is unavailable.
    return false;
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB'];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(1)} ${units[unit]}`;
}

function formatOptions(options: ExtractionOptions | undefined): string {
  if (!options) return 'Extraction options unavailable';
  return optionLabels.map(({ key, title }) => `${title}: ${options[key] ? 'on' : 'off'}`).join(' · ');
}

function App() {
  const [configs, setConfigs] = useState<ConfigOption[]>([]);
  const [configId, setConfigId] = useState('');
  const [callbackConfigured, setCallbackConfigured] = useState(false);
  const [health, setHealth] = useState<boolean | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState(defaultOptions);
  const [history, setHistory] = useState<JobRecord[]>(loadHistory);
  const [activeView, setActiveView] = useState<'workspace' | 'history'>('workspace');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [retrieving, setRetrieving] = useState('');

  const refreshHealth = useCallback(async () => {
    try { setHealth(await getHealth()); } catch { setHealth(false); }
  }, []);

  useEffect(() => {
    getConfigurations()
      .then((result) => {
        setConfigs(result.configurations || []);
        setCallbackConfigured(Boolean(result.callback_configured));
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not load configurations.'));
    void refreshHealth();
  }, [refreshHealth]);

  useEffect(() => {
    const syncHistory = (event: StorageEvent) => {
      if (event.key === HISTORY_KEY) setHistory(loadHistory());
    };
    window.addEventListener('storage', syncHistory);
    return () => window.removeEventListener('storage', syncHistory);
  }, []);

  const ready = useMemo(() => Boolean(file && configId && !busy), [file, configId, busy]);

  function chooseFile(next: File | undefined) {
    setError('');
    setMessage('');
    if (!next) return;
    if (!next.name.toLowerCase().endsWith('.pdf')) {
      setFile(null);
      setError('Choose a PDF file.');
      return;
    }
    setFile(next);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !configId) return;
    setBusy(true);
    setError('');
    setMessage('Sending the PDF to PDFLens…');
    try {
      const job = await submitPdf(file, configId, options);
      const updated = [job, ...history.filter((row) => row.request_id !== job.request_id)].slice(0, 100);
      const saved = saveHistory(updated);
      setHistory(updated);
      setMessage(`PDFLens returned status “${job.status}” for request ${job.request_id}.${saved ? ' Saved in this browser history.' : ' Browser storage is unavailable; this entry will remain until this page closes.'}`);
      setFile(null);
      const input = document.getElementById('pdf-file') as HTMLInputElement | null;
      if (input) input.value = '';
      void refreshHealth();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Submission failed.');
      setMessage('');
    } finally {
      setBusy(false);
    }
  }

  async function onRetrieve(job: JobRecord) {
    setRetrieving(job.request_id);
    setError('');
    setMessage(`Requesting the result for ${job.filename}…`);
    try {
      const result = await retrieveZip(job.request_id);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = result.filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      const updated = history.map((row) => row.request_id === job.request_id
        ? { ...row, retrieved_at: new Date().toISOString(), result_filename: result.filename }
        : row);
      saveHistory(updated);
      setHistory(updated);
      setMessage(`Downloaded the result ZIP for ${job.filename}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not retrieve the ZIP result.');
      setMessage('');
    } finally {
      setRetrieving('');
    }
  }

  function clearHistory() {
    saveHistory([]);
    setHistory([]);
    setMessage('Browser request history cleared.');
  }

  function renderHistoryTable(rows: JobRecord[]) {
    if (!rows.length) return <div className="empty-state"><span>◷</span><b>No submitted requests yet</b><small>Successful submissions from this browser will be saved here.</small></div>;
    return <div className="table-wrap"><table><thead><tr><th>DOCUMENT</th><th>REQUEST ID</th><th>PDFLENS STATUS</th><th>SUBMITTED</th><th>RESULT ZIP</th><th /></tr></thead><tbody>{rows.map((job) => <tr key={job.request_id}>
      <td><div className="doc-name"><span>PDF</span><div><b>{job.filename}</b><small>{formatBytes(job.size)} · {job.config}</small><small className="option-summary" title={formatOptions(job.options)}>{formatOptions(job.options)}</small></div></div></td>
      <td><code title={job.request_id}>{job.request_id}</code></td>
      <td><span className="status-pill">{job.status}</span></td>
      <td>{formatDate(job.submitted_at)}</td>
      <td>{job.retrieved_at ? <span className="retrieved-label" title={job.retrieved_at}>Downloaded</span> : <span className="pending-label">Not downloaded</span>}</td>
      <td><button className="retrieve-button" disabled={Boolean(retrieving)} onClick={() => void onRetrieve(job)}>{retrieving === job.request_id ? 'Requesting…' : job.retrieved_at ? 'Download again ↓' : 'Get ZIP ↓'}</button></td>
    </tr>)}</tbody></table></div>;
  }

  const retrievedCount = history.filter((job) => Boolean(job.retrieved_at)).length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="PDFLens home"><span className="brand-mark">P</span><span>PDFLens<small>DOCUMENT WORKSPACE</small></span></a>
        <div className="nav-caption">WORKSPACE</div>
        <button className={`nav-link ${activeView === 'workspace' ? 'selected' : ''}`} onClick={() => setActiveView('workspace')}><span>＋</span> New processing</button>
        <button className={`nav-link ${activeView === 'history' ? 'selected' : ''}`} onClick={() => setActiveView('history')}><span>◷</span> Request history <em>{history.length}</em></button>
        <div className="sidebar-bottom"><span className={`pulse ${health ? 'online' : health === false ? 'offline' : ''}`} />
          <span><b>{health ? 'PDFLens available' : health === false ? 'PDFLens unavailable' : 'Checking service'}</b><small>Hosted service connection</small></span>
          <button className="refresh" title="Check service" onClick={() => void refreshHealth()}>↻</button>
        </div>
      </aside>

      <main id="top" className="main">
        <header className="topbar"><span>Workspace <i>/</i> {activeView === 'workspace' ? 'New processing' : 'Request history'}</span><span className="secure-label"><b>●</b> Secure API connection</span></header>
        {(error || message) && <div className={`notice ${error ? 'notice-error' : 'notice-info'}`} role="status"><span>{error ? '!' : 'i'}</span><div>{error || message}</div><button onClick={() => { setError(''); setMessage(''); }} aria-label="Dismiss">×</button></div>}
        {activeView === 'workspace' ? <>
        <section className="intro"><div><div className="eyebrow">DOCUMENT PROCESSING</div><h1>Process a PDF</h1><p>Send a document to your hosted PDFLens service and retrieve the result package when it’s ready.</p></div>
          <button className="outline-button" onClick={() => void refreshHealth()}>↻ <span>Check connection</span></button></section>

        <section className="summary-grid" aria-label="Request history summary">
          <article className="summary-card"><span>Requests saved in this browser</span><b>{history.length}</b><small>Successful PDFLens submissions</small></article>
          <article className="summary-card"><span>Result ZIPs downloaded</span><b>{retrievedCount}</b><small>Recorded for this browser</small></article>
          <article className="summary-card"><span>Service</span><b className={health ? 'summary-online' : health === false ? 'summary-offline' : ''}>{health ? 'Available' : health === false ? 'Unavailable' : 'Checking'}</b><small>Live health API response</small></article>
        </section>

        <div className="layout">
          <form id="upload" className="panel form-panel" onSubmit={onSubmit}>
            <div className="panel-heading"><span className="step">01</span><div><h2>Select a PDF</h2><p>Choose the document to submit for processing.</p></div></div>
            <label className={`drop-area ${file ? 'has-file' : ''}`} htmlFor="pdf-file">
              <input id="pdf-file" type="file" accept="application/pdf,.pdf" onChange={(event) => chooseFile(event.target.files?.[0])} />
              <span className="file-icon">{file ? 'PDF' : '↑'}</span>
              <strong>{file ? file.name : 'Choose a PDF or browse'}</strong>
              <small>{file ? `${formatBytes(file.size)} · Ready to submit` : 'PDF format · File is sent securely to the application server'}</small>
            </label>

            <div className="divider" />
            <div className="panel-heading compact"><span className="step">02</span><div><h2>Processing settings</h2><p>Choose a configuration and extraction options.</p></div></div>
            <label className="field-label" htmlFor="config">PDFLens configuration</label>
            <select id="config" value={configId} onChange={(event) => setConfigId(event.target.value)}>
              <option value="">{configs.length ? 'Choose a configuration' : 'No configurations available'}</option>
              {configs.map((config) => <option key={config.id} value={config.id}>{config.label}</option>)}
            </select>
            <div className="field-help">Configuration choices are managed by your application administrator.</div>
            <div className="options-grid">
              {optionLabels.map(({ key, title, note }) => <label key={key} className="option">
                <input type="checkbox" checked={options[key]} onChange={(event) => setOptions((current) => ({ ...current, [key]: event.target.checked }))} />
                <span className="fake-check" /> <span className="option-copy"><b>{title}</b><small>{note}</small></span>
              </label>)}
            </div>
            <div className="callback-note"><span>i</span><span>Callback URL {callbackConfigured ? 'is configured by your administrator.' : 'is not configured (optional).'}</span></div>
            <div className="submit-row"><span>Your file remains in the configured shared storage.</span><button className="primary-button" disabled={!ready}>{busy ? 'Submitting…' : 'Submit to PDFLens'} <b>→</b></button></div>
          </form>

          <aside className="side-column">
            <section className="panel service-panel"><div className="panel-heading compact"><span className={`service-icon ${health ? 'green' : ''}`}>⌁</span><div><h2>Hosted PDFLens</h2><p>Service connection</p></div></div>
              <div className={`service-status ${health ? 'available' : health === false ? 'unavailable' : ''}`}><span />{health ? 'Available' : health === false ? 'Unavailable' : 'Checking'}</div>
              <button className="text-button" onClick={() => void refreshHealth()}>Check health endpoint <b>↗</b></button>
            </section>
            <section className="panel info-panel"><div className="info-symbol">ZIP</div><h3>Result package</h3><p>When processing is complete, retrieve the ZIP using the request ID returned by PDFLens.</p><ul><li>Results are requested manually</li><li>The original ZIP is downloaded</li><li>Request history stays in this browser</li></ul></section>
            <section className="privacy-note"><span>◇</span><p><b>Credentials stay on the server</b><br />The browser calls this app’s backend. PDFLens API URLs and credentials are not placed in the UI.</p></section>
          </aside>
        </div>

        <section id="activity" className="panel activity-panel"><div className="activity-heading"><div><div className="eyebrow">LOCAL TO THIS BROWSER</div><h2>Recent requests <span>{history.length}</span></h2></div><div className="activity-actions"><button className="text-button" onClick={() => setActiveView('history')}>View full history →</button>{history.length > 0 && <button className="text-button clear-button" onClick={clearHistory}>Clear</button>}</div></div>
          {renderHistoryTable(history.slice(0, 5))}
          <div className="history-footnote">Requests are saved in this browser and remain after refresh. Status is shown exactly as returned by PDFLens; the UI does not poll for updates.</div>
        </section>
        </> : <>
          <section className="intro history-intro"><div><div className="eyebrow">LOCAL TO THIS BROWSER</div><h1>Request history</h1><p>Successful submissions and result downloads saved on this browser.</p></div>
            {history.length > 0 && <button className="outline-button" onClick={clearHistory}>Clear history</button>}
          </section>
          <section className="panel activity-panel full-history"><div className="activity-heading"><div><h2>Saved requests <span>{history.length}</span></h2></div><span className="local-storage-tag">Stored in this browser</span></div>
            {renderHistoryTable(history)}
            <div className="history-footnote">History is local to this browser profile. It does not synchronize across devices and does not store PDF or ZIP contents.</div>
          </section>
        </>}
        <footer>PDFLens UI · Hosted service mode <span>API configuration is managed server-side</span></footer>
      </main>
    </div>
  );
}

export default App;
