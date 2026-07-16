const fs = require('fs');
const exe = String.raw`C:\Users\Sozer\Emsal-mcp\.venv\Scripts\emsal-mcp-server.exe`;
const entry = { command: exe, args: [] };

const files = [
  // work2
  'C:/Users/Sozer/.claude-work2/.claude.json',
  'C:/Users/Sozer/AppData/Roaming/Claude-Work2/claude_desktop_config.json',
  // work
  'C:/Users/Sozer/.claude-work/.claude.json',
  'C:/Users/Sozer/AppData/Roaming/Claude-Work/claude_desktop_config.json',
  // personal
  'C:/Users/Sozer/.claude/.claude.json',
  'C:/Users/Sozer/AppData/Roaming/Claude/claude_desktop_config.json',
];

for (const p of files) {
  if (!fs.existsSync(p)) { console.log('YOK, atlandi:', p); continue; }
  const raw = fs.readFileSync(p, 'utf8');
  const d = JSON.parse(raw);
  d.mcpServers = d.mcpServers || {};
  if (d.mcpServers['emsal-mcp']) { console.log('ZATEN EKLI:', p); continue; }
  fs.writeFileSync(p + '.bak-emsal', raw);
  d.mcpServers['emsal-mcp'] = entry;
  fs.writeFileSync(p, JSON.stringify(d, null, 2));
  console.log('EKLENDI:', p);
}
