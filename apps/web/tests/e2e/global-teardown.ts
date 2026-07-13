import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../../../', import.meta.url))

export default function globalTeardown() {
  const result = spawnSync('bash', [`${repositoryRoot}/scripts/e2e_api.sh`, 'cleanup'], {
    cwd: repositoryRoot,
    encoding: 'utf-8',
    env: process.env,
  })
  if (result.status !== 0) {
    throw new Error(`E2E cleanup failed:\n${result.stderr || result.stdout}`)
  }
}
