关于 OpenAPI 类型生成

# 要点

| 项 | 说明 |
|----|------|
| **生成脚本** | `frontend/scripts/generate-types.mjs`：用仓库内绝对路径调用 `openapi-typescript`，避免 Windows 下相对路径跑飞。 |
| **本地校验** | `npm run verify:generated-types`：先再生成一遍，再在仓库根执行 `git diff --exit-code -- frontend/src/api/generated/`。 |
| **npm** | `frontend/package.json` 增加 `openapi-typescript`、`generate:types` / `verify:generated-types`。 |
| **generated** | `frontend/src/api/generated/{cases,recommendations,feedback}.ts`（禁止手改）。 |
| **Service** | `cases.ts` / `recommendations.ts` / `feedback.ts`：路径与 design 一致（`/api/a3-cases`、`/api/recommendations/similar-cases`、`/api/recommendation-feedback`）；反馈 service 注入 `anonymous_user` 与 `admin_web`。 |
| **测试** | `tests/api/cases.test.ts`、`recommendations.test.ts`、`feedback.test.ts` 覆盖路径与反馈注入。 |
| **CI** | `.github/workflows/frontend-ci.yml`：`npm ci` → `verify:generated-types` → `npm test` → `npm run build`（在 `frontend/**` 或 `docs/contracts/**` 变更时触发）。 |
