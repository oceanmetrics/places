// make `env` from cloudflare:test carry the worker's bindings
import type { Env as WorkerEnv } from '../src/env'

declare global {
  namespace Cloudflare {
    interface Env extends WorkerEnv {}
  }
}
