import { spawnSync } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

const BUILD_LOCK_DIRNAME = '.playwright-vite-build.lock'

async function acquireBuildLock(cwd) {
  const lockDir = path.join(cwd, BUILD_LOCK_DIRNAME)
  while (true) {
    try {
      await mkdir(lockDir)
      return lockDir
    } catch (error) {
      if (error?.code !== 'EEXIST') {
        throw error
      }
      await delay(250)
    }
  }
}

export async function runLockedBuild(getBuildCommand, cwd = process.cwd()) {
  const lockDir = await acquireBuildLock(cwd)
  try {
    const { command, args } = getBuildCommand()
    const result = spawnSync(command, args, {
      cwd,
      encoding: 'utf8'
    })

    if (result.status !== 0) {
      throw new Error(result.stderr || result.stdout || 'pnpm build failed')
    }
  } finally {
    await rm(lockDir, {
      recursive: true,
      force: true
    })
  }
}
