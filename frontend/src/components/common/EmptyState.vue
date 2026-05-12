<template>
  <div class="empty-state" role="status">
    <div class="empty-icon" aria-hidden="true">
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="32" cy="32" r="30" stroke="#ddd" stroke-width="2" fill="none"/>
        <path d="M32 20v24M20 32h24" stroke="#ddd" stroke-width="2" stroke-linecap="round"/>
      </svg>
    </div>
    <p class="empty-message">{{ title }}</p>
    <p v-if="description" class="empty-description">{{ description }}</p>
    <slot name="action"></slot>
  </div>
</template>

<script setup lang="ts">
/**
 * EmptyState 组件
 *
 * 通用空状态展示组件
 * 遵循 design.md § Components and Interfaces 和 requirements.md § 6.2（状态可观察）
 */

interface Props {
  title?: string;
  description?: string;
}

withDefaults(defineProps<Props>(), {
  title: '暂无数据',
  description: '',
});
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  min-height: 300px;
  text-align: center;
}

.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.5;
}

.empty-message {
  color: #666;
  font-size: 1rem;
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.empty-description {
  color: #999;
  font-size: 0.875rem;
  max-width: 400px;
  line-height: 1.5;
}
</style>
