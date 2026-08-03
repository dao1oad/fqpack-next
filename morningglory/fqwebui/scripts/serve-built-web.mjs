import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer, request as httpRequest } from 'node:http'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..', 'web')
const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`
const repoRoot = path.resolve(scriptDir, '..', '..', '..')
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.svg':'image/svg+xml'}
const apiBaseUrl = typeof process !== 'undefined'
  ? process.env.FQWEBUI_API_BASE_URL
  : ''
const apiTarget = new URL(apiBaseUrl || 'http://127.0.0.1:15000')
const runtimeEnv = typeof process !== 'undefined' ? process.env : {}
function resolvePath(urlPath) {
  const clean = decodeURIComponent((urlPath || '/').split('?')[0]).replace(/^\/+/, '')
  let file = path.resolve(root, clean)
  if (file !== root && !file.startsWith(rootWithSep)) return null
  if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, 'index.html')
  if (!existsSync(file) && !path.extname(file)) file = path.join(root, 'index.html')
  return (file === root || file.startsWith(rootWithSep)) && existsSync(file) ? file : null
}
function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {'content-type': 'application/json; charset=utf-8'})
  res.end(JSON.stringify(payload))
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}
async function handleLocalTdxImport(req, res) {
  if (req.method !== 'POST') {
    sendJson(res, 405, {code: 'method_not_allowed', message: 'method not allowed'})
    return
  }
  let body
  try {
    body = JSON.parse(await readBody(req) || '{}')
  } catch (error) {
    sendJson(res, 400, {code: 'invalid_json', message: error.message})
    return
  }
  const items = Array.isArray(body.items) ? body.items : []
  if (!items.length) {
    sendJson(res, 400, {code: 'empty_items', message: '没有匹配结果，通达信旧分组已保留'})
    return
  }
  const script = `
import json
import os
import sys
from pathlib import Path
from freshquant.clx_daily_selection.tdx_export import write_clx_tdx_group

payload = json.load(sys.stdin)
items = payload.get("items") or []
tdx_home = str(payload.get("tdx_home") or os.environ.get("FQWEBUI_TDX_HOME") or os.environ.get("TDX_HOME") or "").strip()
if not tdx_home:
    for candidate in ("D:/new_tdx", "G:/new_haitong", "D:/tdx_biduan"):
        if (Path(candidate) / "T0002" / "blocknew").exists():
            tdx_home = candidate
            break
symbols = [{"asset_type": str(item.get("asset_type") or "stock"), "symbol": str(item.get("symbol") or "")} for item in items]
result = write_clx_tdx_group(symbols, tdx_home=tdx_home or None)
result.update({
    "requested_count": len(items),
    "scope_id": str(payload.get("scope_id") or ""),
    "trade_date": str(payload.get("trade_date") or ""),
    "tdx_home": tdx_home,
    "adapter": "serve-built-web-local-tdx",
})
print(json.dumps(result, ensure_ascii=False))
`
  const child = spawn('uv', ['run', 'python', '-c', script], {
    cwd: repoRoot,
    env: {...runtimeEnv},
    windowsHide: true,
  })
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8') })
  child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8') })
  child.stdin.end(JSON.stringify(body))
  child.on('error', (error) => {
    sendJson(res, 500, {code: 'tdx_adapter_failed', message: error.message})
  })
  child.on('close', (code) => {
    if (code !== 0) {
      const message = stderr.trim().split(/\r?\n/).slice(-1)[0] || `uv python exited with ${code}`
      sendJson(res, 500, {code: 'tdx_adapter_failed', message})
      return
    }
    try {
      sendJson(res, 200, JSON.parse(stdout))
    } catch (error) {
      sendJson(res, 500, {code: 'tdx_adapter_invalid_output', message: error.message, stdout, stderr})
    }
  })
}
const server = createServer((req, res) => {
  if ((req.url || '').split('?')[0] === '/api/clx-evaluator/tdx-sync-group') {
    handleLocalTdxImport(req, res)
    return
  }
  if ((req.url || '').startsWith('/api/')) {
    const proxyReq = httpRequest({
      protocol: apiTarget.protocol,
      hostname: apiTarget.hostname,
      port: apiTarget.port,
      method: req.method,
      path: req.url,
      headers: {
        ...req.headers,
        host: apiTarget.host,
      },
    }, (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers)
      proxyRes.pipe(res)
    })
    proxyReq.on('error', (error) => {
      res.writeHead(502, {'content-type': 'application/json; charset=utf-8'})
      res.end(JSON.stringify({code: 'api_proxy_failed', message: error.message}))
    })
    req.pipe(proxyReq)
    return
  }
  const file = resolvePath(req.url || '/')
  if (!file) { res.writeHead(404); res.end('not found'); return }
  res.writeHead(200, {'content-type': types[path.extname(file)] || 'application/octet-stream'})
  createReadStream(file).pipe(res)
})
server.listen(18080, '127.0.0.1', () => console.log(`serving ${root} at http://localhost:18080/`))
