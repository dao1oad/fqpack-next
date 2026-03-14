import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'

const BUILD_LOCK_DIRNAME = '.playwright-vite-build.lock'
const PLAYWRIGHT_VITE_DIRNAME = '.playwright-vite'

function normalizeSpecReference(specReference) {
  if (specReference instanceof URL) {
    return fileURLToPath(specReference)
  }

  if (typeof specReference === 'string' && specReference.startsWith('file:')) {
    return fileURLToPath(specReference)
  }

  return specReference
}

function sanitizeSpecName(specPath) {
  return path
    .basename(specPath, path.extname(specPath))
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
}

export function createIsolatedViteArtifactsContext(specReference, cwd = process.cwd()) {
  const specPath = normalizeSpecReference(specReference)
  const relativeSpecPath = path.relative(cwd, specPath) || path.basename(specPath)
  const specHash = createHash('sha1').update(relativeSpecPath).digest('hex').slice(0, 8)
  const outDirRelative = path.join(
    PLAYWRIGHT_VITE_DIRNAME,
    `${sanitizeSpecName(specPath)}-${specHash}`
  )

  return {
    outDirRelative,
    outDir: path.join(cwd, outDirRelative)
  }
}

export function appendViteOutDirArgs(args, outDir) {
  const nextArgs = [...args]
  if (outDir) {
    nextArgs.push('--outDir', outDir)
  }
  return nextArgs
}

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

export async function runLockedBuild(getBuildCommand, cwd = process.cwd(), { outDir } = {}) {
  const lockDir = await acquireBuildLock(cwd)
  try {
    const { command, args } = getBuildCommand()
    const commandArgs = appendViteOutDirArgs(args, outDir)
    const buildResult = spawnSync(command, commandArgs, {
      cwd,
      encoding: 'utf8'
    })

    if (buildResult.status !== 0) {
      throw new Error(buildResult.stderr || buildResult.stdout || 'pnpm build failed')
    }
  } finally {
    await rm(lockDir, {
      recursive: true,
      force: true
    })
  }
}
