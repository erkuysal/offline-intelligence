export interface SseEvent {
  event: string
  data: string
}

export interface SseParser {
  feed(chunk: string): void
  finish(): void
}

export function createSseParser(onEvent: (event: SseEvent) => void): SseParser {
  let buffer = ''

  function dispatch(frame: string) {
    let event = 'message'
    const data: string[] = []

    for (const line of frame.split(/\r\n|\r|\n/)) {
      if (!line || line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator === -1 ? line : line.slice(0, separator)
      let value = separator === -1 ? '' : line.slice(separator + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value || 'message'
      if (field === 'data') data.push(value)
    }

    if (data.length > 0) onEvent({ event, data: data.join('\n') })
  }

  function drain(remaining = false) {
    let boundary = buffer.search(/\r\n\r\n|\n\n|\r\r/)
    while (boundary !== -1) {
      const separator = buffer.slice(boundary).match(/^(?:\r\n\r\n|\n\n|\r\r)/)?.[0] ?? ''
      dispatch(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + separator.length)
      boundary = buffer.search(/\r\n\r\n|\n\n|\r\r/)
    }
    if (remaining && buffer) {
      dispatch(buffer)
      buffer = ''
    }
  }

  return {
    feed(chunk) {
      buffer += chunk
      drain()
    },
    finish() {
      drain(true)
    },
  }
}
