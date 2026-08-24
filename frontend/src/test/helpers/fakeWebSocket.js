// round35 T-P1#8 (docs/round35-architecture-review.md §16.7-P1-8):
// 三份重复的 FakeWebSocket（marketStore.p1-1 / wsAndSourceGuards / useNewsWS）
// 收敛为共享测试基建。保守超集设计：
// - 构造即 OPEN=1（对齐 p1-1/guards 原语义；useNewsWS 的显式 _open() 兼容）；
// - sent 记录 + instances 登记 + _open/_message 测试助手（对齐 news 用法）；
// - 完整 readyState 静态常量 + 实例级 OPEN getter。
export class FakeWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSING = 2
  static CLOSED = 3
  static instances = []

  static reset() {
    FakeWebSocket.instances = []
  }

  sent = []

  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.OPEN
    this.onopen = null
    this.onmessage = null
    this.onclose = null
    this.onerror = null
    FakeWebSocket.instances.push(this)
  }

  get OPEN() {
    return FakeWebSocket.OPEN
  }

  send(data) {
    this.sent.push(data)
  }

  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return
    this.readyState = FakeWebSocket.CLOSED
    if (this.onclose) this.onclose()
  }

  // ── test helpers ──
  _open() {
    this.readyState = FakeWebSocket.OPEN
    if (this.onopen) this.onopen()
  }

  _message(data) {
    if (this.onmessage) this.onmessage({ data })
  }
}
