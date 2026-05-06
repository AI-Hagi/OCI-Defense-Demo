# ADR-0002: OCI DevOps build pipeline unbreak (2026-05-06)

## Status

Accepted — verified live with a successful frontend OCIR push at 16:34 UTC on 2026-05-06. Tagged as `v0.2.0-pipeline-unbreak`.

## Context

Around **2026-05-02** the OCI DevOps build pipelines silently stopped producing successful runs. Every push to `main` (and every manual trigger) failed within 30–60 seconds. No buildspec, application code, or pipeline definition had been edited the day this started.

Investigation on 2026-05-06 traced this to **OCI rolling out a new `OL8_X86_64_STANDARD_10` build runner image** with multiple breaking changes:

| Symptom in our pipeline | Underlying runner-image change |
|---|---|
| `EXEC: Error: unable to find user default: no matching entries in passwd file` | The `default` user was removed from `/etc/passwd` |
| `cd: /workspace/frontend: No such file or directory` | Source-collections are no longer flattened into `$OCI_WORKSPACE_DIR`; they live under `$OCI_PRIMARY_SOURCE_DIR` (e.g. `/workspace/src/`) |
| `[vite]: Rollup failed to resolve import "axios"` only inside Docker, despite the host build seeing 2640 modules | The host's OL8/glibc-built `node_modules` was clobbering the alpine container's musl-built install via `COPY . .`; previously not an issue because of subtle differences in how `npm ci` ran |
| `EMFILE: too many open files` while bundling `cesium/Source/Widgets/widgets.css` | Default container nofile limit ≈ 1024; cesium ships ~15k files |
| `Error: template: ... at <.Id>: can't evaluate field Id in type interface{}` and `at <index . 0>: can't index item of type entities.ImageInspectReport` | The runner uses **podman** (not Docker), which returns a typed struct from `docker inspect`, not an array; existing `--format='{{index .Id}}'` failed |
| Build-cache reuse of pre-fix layers across runs | Podman shared-storage was reusing intermediate layers from before any of these fixes existed |
| `Unable to save docker image artifact localhost/$IMAGE_NAME:$IMAGE_TAG in the build spec file.` | OCI's `outputArtifacts.location` parser requires the `${VAR}` brace form for variable interpolation; bare `$VAR` is treated literally; podman tags built images under the `localhost/` registry prefix |
| `denied: User UserId(...devopsbuildpipeline...) not authorized` | Pre-existing IAM gap: `devops-build-pipelines-read-mirror-policy` only granted `read repos`, not `manage repos` (i.e. push). Worked previously because images were being pushed manually from the dev VM under instance-principal auth. |

## Decision

Land a chain of nine narrowly-scoped PRs to the buildspecs, plus one IAM policy, to bring the pipeline back to a deterministic green state. Each PR addresses **one** observable symptom, validated by a manual build trigger before moving on.

| PR | Fix | Verified by |
|---|---|---|
| **#57** | (preceding hotfix) common-coalition whitelist restored in `coalition_security_policy` | `verify-coalition-vpd.sh --uc 10` passing |
| **#59** | Remove `runAs: default` from all 13 buildspecs | Step `Show build context` advanced from FAILED → SUCCEEDED |
| **#61** | Source paths reference `$OCI_PRIMARY_SOURCE_DIR` (not `$OCI_WORKSPACE_DIR`) | `Ensure Dockerfile present` advanced FAILED → SUCCEEDED |
| **#63** | Add `frontend/.dockerignore` excluding `node_modules`, `dist`, etc. | `Docker build` reached `npm run build` |
| **#65** | (initial inspect format change — superseded by #71) | — |
| **#67** | Replace `--build-arg BUILDKIT_INLINE_CACHE=1` with `--no-cache` | Builds became deterministic; new failure modes exposed |
| **#69** | Add `--ulimit nofile=65536:65536` to `docker build` | Cesium CSS pipeline no longer EMFILEs |
| **#71** | Simplify inspect format to `--format='{{.Id}}'` (podman returns struct directly) | `Image SHA256 + traceability` advanced FAILED → SUCCEEDED |
| **#73** | Prefix `outputArtifacts.location` with `localhost/` (podman tagging convention) | OCI's lookup error became more specific |
| **#75** | Use `${IMAGE_NAME}:${IMAGE_TAG}` brace form for OCI's parser | `SAVE_OUTPUT_ARTIFACTS` advanced FAILED → SUCCEEDED |
| **IAM** | New policy `devops-build-pipelines-manage-ocir-policy`: `Allow any-user to manage repos in compartment <id> where all {request.principal.type='devopsbuildpipeline', request.principal.compartment.id='<id>'}` | `deliver-frontend` stage advanced FAILED → SUCCEEDED; image landed in OCIR |

Verified end-to-end with build run `amaaaaaaqfczboqamga2imlis6rq3mxzbqbxr4v6ugx7z4egcwynn2qmua6a` at 16:34 UTC: both stages SUCCEEDED, image pushed to `fra.ocir.io/fri3jnkhmoew/sovdefence/frontend:<commit>`.

## Consequences

**Positive:**
- Auto-triggered builds on `main` push produce OCIR-published images again.
- Builds are deterministic (no cache reuse) at the cost of ~30-60s per build.
- The IAM policy is narrowly scoped to the `oci-defence-demo` compartment and to `devopsbuildpipeline` principals — no broader blast radius.
- Future buildspecs derived from these (the 5 buildspecs without registered pipelines: `jamming-poller`, `ports-proxy`, `sentinel-proxy`, `tle-proxy`, `uc4-chat`) inherit all the fixes via the unified sed patches in PRs #59, #61, #67, #69, #71, #73, #75.

**Negative:**
- Eight buildspec changes happened in quick succession. Each PR was small but the timeline is dense — future maintainers should read this ADR before debugging a Docker step regression.
- `--no-cache` makes builds slower. If we hit time-budget pressure later, revisit by introducing a registry-pull cache via `--cache-from fra.ocir.io/.../sovdefence/frontend:cache` instead of inline cache.
- The OL8 runner image change came with **no advance notice** from OCI. Future runner-image rolls might do this again. Mitigation: keep this ADR's symptom-table as a reference for future "why is the build suddenly failing" diagnostics.

## Known follow-up: Python service pipelines

After the chain landed, all 7 service pipelines (`build-flights-proxy`, `build-ais-multiplexer`, `build-compliance`, `build-supply-chain`, `build-osint`, `build-doc-intel`, `build-geoint`) were manually triggered. All advanced past `Show build context`, `Lint (pyflakes)`, and into `Unit tests (pytest)` — proving PR #59 + #61 fixes apply to them too — but failed there with:

```
ProxyError('Cannot connect to proxy.', ...): /simple/pytest/
ERROR: Could not find a version that satisfies the requirement pytest==8.3.3
```

The OL8 build runner appears to have an `HTTP_PROXY`/`HTTPS_PROXY` env baked in that points at a now-unreachable host. `npm ci` for the frontend uses a different code path that bypasses this. Fixing it requires either:

- Adding `unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy` before `pip install` in each Python buildspec
- OR baking pip deps into the Dockerfile so the build runner doesn't need PyPI at runtime
- OR setting `pip --proxy "" install ...` to override

**Resolved in PR #80 (post-v0.2.0):** PR #78's `unset HTTP_PROXY` didn't help — pip kept hitting the proxy via `/etc/pip.conf` or similar. PR #80 added `pip install --proxy ""` as a CLI override on every pip command in all 12 service/proxy buildspecs. Verified: compliance pipeline pushes to OCIR end-to-end after #80.

**Service pipeline post-fix status (manual triggers, 18:11–18:19 UTC):**

| Pipeline | Status | Notes |
|---|---|---|
| compliance | ✅ | Image in OCIR |
| flights-proxy | ✅ | |
| supply-chain | ✅ | |
| osint | ✅ | |
| ais-multiplexer | ❌ | Fails at `pytest`; pip install OK, likely real test failures (WebSocket fixtures) |
| doc-intel | ❌ | Fails at `pytest`; likely real test failures (OCI Doc Understanding mocks) |
| geoint | ❌ | Fails at `pytest`; likely real test failures (Oracle DB integration tests) |

The 3 failing pipelines share infra fixes already on main; their failures are at the application-test layer (specific service code), not pipeline configuration. Out of scope for v0.2.0 unbreak — addressing each requires per-service test investigation. For now, the demo runs on `v0.1.0-demo-2026-05-04` images (manually built) and the OCI DevOps pipeline produces fresh images for compliance, flights-proxy, supply-chain, osint, and frontend on every main push.

## Operational notes

- `scripts/verify-coalition-vpd.sh --uc 10` PASSes against `sovdef26` ATP after PR #57 hotfix and the v2 `_shared` baseline migration documented in PR #56's body.
- The OCI repository mirror lags GitHub. After every main push, force `oci devops repository mirror --repository-id <ocid>` to ensure the next auto-triggered build pulls the latest commit. (Otherwise the build may run against a stale buildspec.)
- The deliver stage's `image-uri` already used `${IMAGE_TAG}`. The buildspec's `outputArtifacts.location` must match this brace style.
- Manual builds from the dev VM (the prior workaround during the broken window) used the user's instance-principal — that path remains available as a backup.

## References

- Tag: `v0.2.0-pipeline-unbreak`
- Live verification run: `ocid1.devopsbuildrun.oc1.eu-frankfurt-1.amaaaaaaqfczboqamga2imlis6rq3mxzbqbxr4v6ugx7z4egcwynn2qmua6a`
- IAM policy OCID: `ocid1.policy.oc1..aaaaaaaa3osoayd4saupup7hqvf2pmn5frnsp72xqc2bgmhcscbeaj7qfd4q`
- Pipeline OCID (build-frontend): `ocid1.devopsbuildpipeline.oc1.eu-frankfurt-1.amaaaaaaqfczboqabe2sntftvelaerfi6tv5yx4ltvwc6ccnxk6pqv4gtaiq`
