import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AdminLayout from '../components/layout/AdminLayout.vue'
import CaseListPage from '../pages/CaseListPage.vue'
import CaseCreatePage from '../pages/CaseCreatePage.vue'
import CaseDetailPage from '../pages/CaseDetailPage.vue'
import CaseEditPage from '../pages/CaseEditPage.vue'
import RecommendationPage from '../pages/RecommendationPage.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/cases'
  },
  {
    path: '/cases',
    component: AdminLayout,
    children: [
      {
        path: '',
        name: 'case-list',
        meta: { breadcrumb: '案例知识库 / 案例列表' },
        component: CaseListPage
      },
      {
        path: 'create',
        name: 'case-create',
        meta: { breadcrumb: '案例知识库 / 创建案例' },
        component: CaseCreatePage
      },
      {
        path: ':id/edit',
        name: 'case-edit',
        meta: { breadcrumb: '案例知识库 / 编辑案例' },
        component: CaseEditPage
      },
      {
        path: ':id',
        name: 'case-detail',
        meta: { breadcrumb: '案例知识库 / 案例详情' },
        component: CaseDetailPage
      }
    ]
  },
  {
    path: '/recommendations',
    component: AdminLayout,
    children: [
      {
        path: '',
        name: 'recommendations',
        meta: { breadcrumb: '检索推荐 / 相似案例检索' },
        component: RecommendationPage
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
