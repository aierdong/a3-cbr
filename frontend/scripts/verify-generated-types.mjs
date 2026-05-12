/**
 * 重新生成契约类型并校验 `frontend/src/api/generated/` 与当前提交一致。
 * 在仓库根目录执行：`npm run verify:generated-types --prefix frontend`
 */
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(__dirname, '..')
const repoRoot = join(frontendRoot, '..')
const generateScript = join(frontendRoot, 'scripts', 'generate-types.mjs')

execFileSync(process.execPath, [generateScript], { stdio: 'inherit' })
execFileSync('git', ['diff', '--exit-code', '--', 'frontend/src/api/generated/'], {
  stdio: 'inherit',
  cwd: repoRoot,
})
