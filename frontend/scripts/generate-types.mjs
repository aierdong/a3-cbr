/**
 * 从仓库根目录的 docs/contracts OpenAPI 文件生成 frontend/src/api/generated/*.ts
 * 使用绝对路径，避免在 Windows 上因工作目录不同而解析到错误位置。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(__dirname, '..')
const repoRoot = join(frontendRoot, '..')
const outDir = join(frontendRoot, 'src', 'api', 'generated')

mkdirSync(outDir, { recursive: true })

const openapiTsCli = join(frontendRoot, 'node_modules', 'openapi-typescript', 'bin', 'cli.js')
if (!existsSync(openapiTsCli)) {
  throw new Error(`未找到 openapi-typescript CLI：${openapiTsCli}（请先在前端目录执行 npm install）`)
}

const jobs = [
  [join(repoRoot, 'docs', 'contracts', 'a3-case-management.openapi.yaml'), join(outDir, 'cases.ts')],
  [join(repoRoot, 'docs', 'contracts', 'cbr-retrieval-recommendation.openapi.yaml'), join(outDir, 'recommendations.ts')],
  [join(repoRoot, 'docs', 'contracts', 'recommendation-feedback.openapi.yaml'), join(outDir, 'feedback.ts')],
]

for (const [input, output] of jobs) {
  execFileSync(process.execPath, [openapiTsCli, input, '-o', output], { stdio: 'inherit' })
}
