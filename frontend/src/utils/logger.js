// 前端统一日志工具。
// 开发环境（import.meta.env.DEV）输出 debug 级别；生产环境只输出 info 及以上。
// 所有日志带统一前缀 [ETF-Surge]，便于在浏览器控制台 / 终端筛选。

const PREFIX = '[ETF-Surge]'

function emit(level, consoleFn, args) {
  consoleFn(PREFIX, level, ...args)
}

export const logger = {
  debug(...args) {
    if (import.meta.env.DEV) emit('DEBUG', console.debug, args)
  },
  info(...args) {
    emit('INFO', console.info, args)
  },
  warn(...args) {
    emit('WARN', console.warn, args)
  },
  error(...args) {
    emit('ERROR', console.error, args)
  },
}

export default logger
