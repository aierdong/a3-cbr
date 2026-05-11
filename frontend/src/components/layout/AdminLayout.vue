<template>
  <div class="admin-layout">
    <nav class="admin-nav">
      <div class="nav-header">
        <h1 class="nav-title">A3 案例管理系统</h1>
      </div>
      <ul class="nav-menu">
        <li>
          <router-link
            to="/cases"
            class="nav-link"
            :class="{ active: isCaseRoute }"
            data-nav="cases"
          >
            案例管理
          </router-link>
        </li>
        <li>
          <router-link
            to="/recommendations"
            class="nav-link"
            :class="{ active: isRecommendationRoute }"
            data-nav="recommendations"
          >
            检索推荐
          </router-link>
        </li>
      </ul>
    </nav>
    <main class="admin-main">
      <div class="breadcrumb" v-if="breadcrumbText">
        <router-link
          v-if="showCaseBackLink"
          :to="{ name: 'case-list' }"
          class="breadcrumb-back"
        >
          返回列表
        </router-link>
        <span class="breadcrumb-text">{{ breadcrumbText }}</span>
      </div>
      <div class="page-container">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 需求 1.2: 保持清晰的当前位置提示
const isCaseRoute = computed(() => {
  return route.path.startsWith('/cases')
})

const isRecommendationRoute = computed(() => {
  return route.path.startsWith('/recommendations')
})

const breadcrumbText = computed(() => {
  const label = route.meta.breadcrumb
  return typeof label === 'string' ? label : ''
})

const showCaseBackLink = computed(() =>
  route.name === 'case-create' ||
  route.name === 'case-detail' ||
  route.name === 'case-edit'
)
</script>

<style scoped>
.admin-layout {
  display: flex;
  width: 100%;
  height: 100%;
}

.admin-nav {
  width: 200px;
  background-color: #2c3e50;
  color: #fff;
  display: flex;
  flex-direction: column;
}

.nav-header {
  padding: 20px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.nav-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.nav-menu {
  list-style: none;
  padding: 16px 0;
  margin: 0;
}

.nav-menu li {
  margin: 0;
}

.nav-link {
  display: block;
  padding: 12px 16px;
  color: rgba(255, 255, 255, 0.7);
  text-decoration: none;
  transition: all 0.2s;
}

.nav-link:hover {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.nav-link.active {
  background-color: rgba(255, 255, 255, 0.15);
  color: #fff;
  font-weight: 500;
}

.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 24px;
  background-color: #fff;
  border-bottom: 1px solid #e0e0e0;
}

.breadcrumb-back {
  flex-shrink: 0;
  font-size: 14px;
  color: #1976d2;
  text-decoration: none;
}

.breadcrumb-back:hover {
  text-decoration: underline;
}

.breadcrumb-text {
  font-size: 14px;
  color: #666;
}

.page-container {
  flex: 1;
  overflow: auto;
  padding: 24px;
}
</style>
