/** 案例列表筛选用的演示门店/品牌数据（与产品演示表一致）。 */

export interface DemoStoreRow {
  store_id: string
  store_name: string
  brand_id: string
  brand_name: string
}

export const DEMO_STORE_ROWS: readonly DemoStoreRow[] = [
  { store_id: 'store-001', store_name: '韭菜园旗舰店', brand_id: 'brand-001', brand_name: '瑞幸咖啡' },
  { store_id: 'store-002', store_name: '长沙海底捞第一店', brand_id: 'brand-002', brand_name: '海底捞' },
  { store_id: 'store-003', store_name: '红红红店', brand_id: 'brand-003', brand_name: '仟吉西饼' },
  { store_id: 'store-004', store_name: '芙蓉苑喜茶旗舰店', brand_id: 'brand-004', brand_name: '喜茶' },
  { store_id: 'store-005', store_name: '火车站老店', brand_id: 'brand-005', brand_name: '全聚德' },
  { store_id: 'store-006', store_name: '黄兴路步行街7店', brand_id: 'brand-006', brand_name: '正新鸡排' },
  { store_id: 'store-007', store_name: '不晓得哪里的店', brand_id: 'brand-007', brand_name: '太二酸菜鱼' },
] as const

export interface DemoBrandOption {
  brand_id: string
  brand_name: string
}

const brandKey = (r: DemoStoreRow) => r.brand_id

export const DEMO_BRAND_OPTIONS: readonly DemoBrandOption[] = (() => {
  const seen = new Set<string>()
  const out: DemoBrandOption[] = []
  for (const r of DEMO_STORE_ROWS) {
    if (seen.has(brandKey(r))) continue
    seen.add(brandKey(r))
    out.push({ brand_id: r.brand_id, brand_name: r.brand_name })
  }
  return out
})()

export function demoStoresForBrand(brandId: string): readonly DemoStoreRow[] {
  if (!brandId.trim()) return DEMO_STORE_ROWS
  return DEMO_STORE_ROWS.filter((r) => r.brand_id === brandId)
}
