<template>
  <div class="loading-state" role="status" aria-live="polite">
    <div class="loading-spinner" aria-hidden="true"></div>
    <p class="loading-message">{{ message }}</p>
    <slot></slot>
  </div>
</template>

<script setup lang="ts">
/**
 * LoadingState 组件
 *
 * 通用加载状态展示组件
 * 遵循 design.md § Components and Interfaces 和 requirements.md § 6.2（状态可观察）
 */

interface Props {
  message?: string;
}

withDefaults(defineProps<Props>(), {
  message: '加载中...',
});
</script>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  min-height: 200px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #3498db;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.loading-message {
  margin-top: 1rem;
  color: #666;
  font-size: 0.875rem;
}
</style>
