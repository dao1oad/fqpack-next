import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer, request as httpRequest } from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..', 'web')
const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.svg':'image/svg+xml'}
const apiBaseUrl = typeof process !== 'undefined'
  ? process.env.FQWEBUI_API_BASE_URL
  : ''
const apiTarget = new URL(apiBaseUrl || 'http://127.0.0.1:15000')
function resolvePath(urlPath) {
  const clean = decodeURIComponent((urlPath || '/').split('?')[0]).replace(/^\/+/, '')
  let file = path.resolve(root, clean)
  if (file !== root && !file.startsWith(rootWithSep)) return null
  if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, 'index.html')
  if (!existsSync(file) && !path.extname(file)) file = path.join(root, 'index.html')
  return (file === root || file.startsWith(rootWithSep)) && existsSync(file) ? file : null
}
const server = createServer((req, res) => {
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
