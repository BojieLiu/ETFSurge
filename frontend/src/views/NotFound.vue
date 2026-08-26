<template>
  <div class="nf-wrap">
    <div class="nf-card">
      <div class="nf-code">404</div>
      <p class="nf-msg">页面不存在或已被移动</p>
      <router-link class="nf-home" to="/">返回市场概览</router-link>
    </div>
  </div>
</template>

<script setup>
// round34-B7: catch-all 兜底视图（批复⑤）
</script>

<style scoped>
.nf-wrap {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.nf-card {
  text-align: center;
  padding: var(--space-6, 40px) var(--space-8, 64px);
  border-radius: 12px;
}
.nf-code {
  font-size: 56px;
  font-weight: 700;
  opacity: 0.35;
  line-height: 1.1;
}
.nf-msg {
  margin: 8px 0 20px;
  opacity: 0.7;
}
.nf-home {
  display: inline-block;
  padding: 8px 18px;
  border-radius: 8px;
  background: var(--accent, #2563eb);
  color: #fff;
  text-decoration: none;
}
</style>
