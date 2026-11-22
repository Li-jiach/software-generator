async function request(path, options) {
  const headers = new Headers(options.headers || {})
  let body = options.body
  if (body && !(body instanceof FormData)) { headers.set('Content-Type', 'application/json'); body = JSON.stringify(body) }
  const response = await fetch('/api' + path, {...options, headers, body, credentials: 'same-origin'})
  if (!response.ok) {
    const result = await response.json().catch(() => ({}))
    if (response.status === 401 && !path.endsWith('/login')) window.dispatchEvent(new Event('session-expired'))
    throw Object.assign(new Error(result.message || result.detail || `请求失败（${response.status}）`), {status:response.status})
  }
  return response
}

export async function api(path, options = {}) {
  return (await request(path, options)).json().catch(() => ({}))
}

export async function downloadFile(path, options, filename) {
  const blob = await (await request(path, options)).blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export async function assistantStream(body, onEvent) {
  const response = await request('/assistant/chat/stream', {method:'POST', body})
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    while (true) {
      const {value, done} = await reader.read()
      if (done) throw new Error('助手回答中断，请重试。')
      buffer += value
      let index
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index)
        buffer = buffer.slice(index + 1)
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'error') throw new Error(event.message)
        if (event.type === 'done') return event
        onEvent(event)
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
export const stamp = value => value ? new Date(value).toLocaleString('zh-CN', {hour12: false}) : '—'
export const statusName = s => ({draft: '填写中', submitted: '待核实', returned: '已退回', approved: '已核实'}[s] || s)
export const fileUrl = (project, file, inline = false) => `/api/projects/${encodeURIComponent(project)}/files/${encodeURIComponent(file)}/download?inline=${inline}`
export const size = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B'
