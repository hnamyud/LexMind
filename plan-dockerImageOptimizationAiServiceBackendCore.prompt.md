## Plan: Docker Image Optimization for ai-service + backend-core

Optimize image size, rebuild speed, and runtime hardening using low-risk changes only (no Alpine/distroless), scoped to local Docker and docker-compose. Prioritize deterministic dependency installs, layer-cache-friendly Dockerfile structure, and removing non-runtime artifacts.

**Steps**
1. Phase 0 - Baseline measurement (blocks all later comparisons): capture current build duration and final image sizes for both services using current Dockerfiles and compose setup.
2. Phase 1 - ai-service quick wins (parallel with step 3): add runtime HEALTHCHECK in [ai-service/Dockerfile](ai-service/Dockerfile) using existing app endpoint behavior from [ai-service/app/api/routes.py](ai-service/app/api/routes.py); keep startup grace suitable for model/service initialization from [ai-service/main.py](ai-service/main.py).
3. Phase 1 - backend-core quick wins (parallel with step 2): add non-root runtime user in [backend-core/Dockerfile](backend-core/Dockerfile) and ensure copied runtime files remain readable/executable; preserve current startup command path.
4. Phase 2 - deterministic and cache-efficient dependency install (depends on 2 and 3):
   1. ai-service: keep buildkit pip cache mount and simplify pip env consistency in [ai-service/Dockerfile](ai-service/Dockerfile) so build intent is explicit and repeatable.
   2. backend-core: switch deps stage from npm install to npm ci in [backend-core/Dockerfile](backend-core/Dockerfile) to enforce lockfile-exact installs and stable layer cache behavior.
5. Phase 2 - reduce runtime payload (depends on 4):
   1. backend-core: strip source map files from runtime output in [backend-core/Dockerfile](backend-core/Dockerfile) after build but before final copy.
   2. backend-core: keep dev dependency pruning (already present) and evaluate adding optional dependency prune only if lockfile/runtime checks pass.
6. Phase 3 - build context hygiene (parallel with step 5): verify and tighten ignore patterns in [ai-service/.dockerignore](ai-service/.dockerignore) and [backend-core/.dockerignore](backend-core/.dockerignore) so local artifacts (logs, caches, temp outputs) cannot inflate context.
7. Phase 3 - compose readiness alignment (depends on 2): add health-aware dependency condition for backend service in [docker-compose.yml](docker-compose.yml) so [backend-core](backend-core/Dockerfile) waits on ai-service health, not only service start.
8. Phase 4 - validate functionality (depends on 5, 6, 7): rebuild and run both services with compose; verify health endpoints, application boot, and inter-service calls stay unchanged.
9. Phase 4 - compare and accept (depends on 8): compare before/after image size and build time, then accept only if improvements are measurable and no runtime regressions appear.

**Relevant files**
- [ai-service/Dockerfile](ai-service/Dockerfile) - optimize runtime hardening, healthcheck, and pip/build cache clarity.
- [ai-service/.dockerignore](ai-service/.dockerignore) - enforce minimal build context for service-scoped build.
- [ai-service/main.py](ai-service/main.py) - reference startup characteristics for healthcheck timing.
- [ai-service/app/api/routes.py](ai-service/app/api/routes.py) - reference existing health endpoint semantics.
- [backend-core/Dockerfile](backend-core/Dockerfile) - npm ci, non-root runtime, source map removal, prune strategy.
- [backend-core/.dockerignore](backend-core/.dockerignore) - prevent unnecessary context payload.
- [backend-core/package-lock.json](backend-core/package-lock.json) - source of truth for deterministic installs with npm ci.
- [docker-compose.yml](docker-compose.yml) - startup dependency/health orchestration between services.

**Verification**
1. Build-time comparison: measure clean and cached builds for both images before/after (same machine, same cache conditions).
2. Size comparison: capture final image sizes and layer histories for both services before/after.
3. Runtime hardening checks: confirm containers run as non-root where planned and still start correctly.
4. Health checks: confirm ai-service healthcheck transitions to healthy and backend startup ordering behaves correctly under compose.
5. Functional smoke tests: call ai-service health endpoint and backend core health/base endpoint; ensure backend can still reach ai-service internal URL.
6. Regression gate: if any change increases failures or startup instability, revert only that change set while keeping other validated optimizations.

**Decisions**
- Included scope: low-risk optimizations for size, rebuild speed, and runtime hardening.
- Excluded scope: Alpine/distroless migration and CI/CD pipeline changes.
- Assumption: no mandatory requirement to keep JS source maps inside production container.
- Assumption: current endpoint behavior in ai-service and backend-core remains contract-compatible after image optimization.

**Further Considerations**
1. If production debugging requires source maps in-container, retain them and prioritize other size reductions first.
2. If non-root runtime causes permission issues, fix ownership during COPY rather than dropping the hardening step.
3. If optional prune breaks runtime, keep only --omit=dev and treat optional deps as required by current dependency graph.
