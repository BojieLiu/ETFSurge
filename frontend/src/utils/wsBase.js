// round35 FE3 (docs/round35-architecture-review.md §14.11/R126-2):
// WS_BASE 单点构造——market/news/task 三路 WS 实现共用，
// 此前同款 IIFE 在三个文件各复制一份（横切关注点分散）。
const proto = location.protocol === 'https:' ? 'wss' : 'ws'
export const WS_BASE = `${proto}://${location.host}/api/v1/ws`
