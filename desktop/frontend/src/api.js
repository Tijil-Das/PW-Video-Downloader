// pywebview js_api wrapper. All calls go through window.pywebview.api.
// Outside pywebview (plain browser dev) these resolve to safe fallbacks.
function call(method, ...args) {
  const api = window.pywebview?.api;
  if (api && typeof api[method] === 'function') return api[method](...args);
  return Promise.resolve(fallback(method));
}

function fallback(method) {
  if (method === 'server_status') return { running: false, port: 9777 };
  if (method === 'list_jobs') return [];
  if (method === 'check_extension') return { installed: false, profiles: [] };
  if (method === 'get_settings')
    return { ws_port: 9777, auto_start_server: true };
  return null;
}

export const api = {
  checkExtension: () => call('check_extension'),
  serverStatus: () => call('server_status'),
  startServer: () => call('start_server'),
  stopServer: () => call('stop_server'),
  listJobs: () => call('list_jobs'),
  getSettings: () => call('get_settings'),
  saveSettings: (patch) => call('save_settings', patch),
  openFolder: (path) => call('open_folder', path),
};
