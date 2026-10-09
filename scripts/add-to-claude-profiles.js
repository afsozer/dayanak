const fs = require('fs');
const os = require('os');
const path = require('path');

// Depo kokundeki .venv; Claude Code ve Claude Desktop profilleri ev dizininden turetilir.
// Ek profil: DAYANAK_CLAUDE_PROFILES ortam degiskeni (noktali virgulle ayrilmis dosya yollari).
const repo = path.resolve(__dirname, '..');
const exe = process.platform === 'win32'
  ? path.join(repo, '.venv', 'Scripts', 'dayanak-server.exe')
  : path.join(repo, '.venv', 'bin', 'dayanak-server');
const entry = { command: exe, args: [] };

const home = os.homedir();
const appData = process.env.APPDATA
  || (process.platform === 'darwin' ? path.join(home, 'Library', 'Application Support') : path.join(home, '.config'));
const files = [
  path.join(home, '.claude', '.claude.json'),
  path.join(home, '.claude.json'),
  path.join(appData, 'Claude', 'claude_desktop_config.json'),
  ...(process.env.DAYANAK_CLAUDE_PROFILES || '').split(';').filter(Boolean),
];

for (const p of files) {
  if (!fs.existsSync(p)) { console.log('YOK, atlandi:', p); continue; }
  const raw = fs.readFileSync(p, 'utf8');
  const d = JSON.parse(raw);
  d.mcpServers = d.mcpServers || {};
  if (d.mcpServers['dayanak']) { console.log('ZATEN EKLI:', p); continue; }
  fs.writeFileSync(p + '.bak-dayanak', raw);
  d.mcpServers['dayanak'] = entry;
  fs.writeFileSync(p, JSON.stringify(d, null, 2));
  console.log('EKLENDI:', p);
}
