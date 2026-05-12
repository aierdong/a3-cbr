<template>
  <div class="error-notice" role="alert">
    <p class="error-message">{{ message }}</p>

    <!-- 操作按钮插槽 -->
    <div v-if="$slots.actions" class="error-actions">
      <slot name="actions"></slot>
    </div>

    <!-- 默认重试按钮 -->
    <div v-else-if="showRetry" class="error-actions">
      <button
        type="button"
        class="error-retry-button"
        data-testid="error-retry"
        @click="handleRetry"
      >
        重试
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ErrorNotice 组件
 *
 * 通用错误提示组件
 * 遵循 design.md § Error Handling 和 requirements.md § 1.4, 6.2, 6.4
 */

interface Props {
  message: string;
  showRetry?: boolean;
}

interface Emits {
  (e: 'retry'): void;
}

withDefaults(defineProps<Props>(), {
  showRetry: false,
});

const emit = defineEmits<Emits>();

function handleRetry(): void {
  emit('retry');
}
</script>

<style scoped>
.error-notice {
  padding: 1rem;
  border-radius: 4px;
  border: 1px solid #e74c3c;
  background-color: #fadbd8;
}

.error-message {
  margin: 0 0 0.5rem 0;
  color: #555;
  font-size: 0.875rem;
  line-height: 1.5;
}

.error-actions {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
}

.error-retry-button {
  padding: 0.5rem 1rem;
  background-color: #3498db;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background-color 0.2s;
}

.error-retry-button:hover {
  background-color: #2980b9;
}

.error-retry-button:active {
  background-color: #21618c;
}
</style>
