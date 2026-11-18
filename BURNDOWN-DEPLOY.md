# Burn-down: Horus security and deployment

Work needed before the first customer engagement. It isn't needed to keep
building features; the feature list is [BURNDOWN.md](BURNDOWN.md).

The goal is that Horus installs in an air-gapped environment from container
images that pass a JFrog Xray scan, and that nothing downloads packages at
start-up.

Status values: Todo / Doing / Done / Blocked / Cut. Estimates are hours.

## A. Dependency and framework security

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| A1 | Next.js 16.2.6 → 16.4.3 or later (security advisories). Moved from BURNDOWN 2.1. | Build and smoke test pass | 1 | Todo |
| A2 | Port the upstream OSIRIS security fixes: image optimizer disabled, tile proxy narrowed, ArcGIS server-side request forgery fix, rate limits that bind. Moved from BURNDOWN 2.2. | Each fix ported or confirmed not applicable | 3 | Todo |
| A3 | Audit pass on every service: `npm audit` (UI, intel, tile server) and `pip-audit` (gateway, memgraph shim, provisioner); fix or record each finding | No unexplained high or critical findings | 3 | Todo |
| A4 | Pin every base image by digest and every package by exact version (lockfiles already pin npm) | Rebuilds are reproducible | 1 | Todo |

## B. One image per service

Each image is built where there is internet access, scanned, and pushed to the
customer's registry (Artifactory). Applications start from the image with no
`npm` or `pip` and no git clone.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| B1 | UI reads the basemap style URL at run time (env var served to the browser), not at build time, so one UI image serves every instance | Same build works with two different tile server URLs | 2 | Todo |
| B2 | Launchers get an offline mode (`HORUS_OFFLINE=1`): use the dependencies in the image, never install, and fail clearly if something is missing | Start with egress blocked succeeds, or names the missing piece | 2 | Todo |
| B3 | `horus-ui` image: multi-stage build; the final stage has the prebuilt `.next`, `public/` and production packages only (no compiler or dev tools) | Image runs `next start`; size recorded | 3 | Todo |
| B4 | `horus-intel` image: resolver plus packages, and an OFAC SDN snapshot file (pairs with BURNDOWN 7.6) | Resolver starts with egress blocked | 2 | Todo |
| B5 | `horus-tileserver` image: tileserver-gl-light, style, fonts, sprites; the basemap `.mbtiles` stays a mounted or uploaded artifact | Tiles served with egress blocked | 2 | Todo |
| B6 | `horus-gateway` image: Python with every gateway package installed | Gateway starts with no `pip install` | 2 | Todo |
| B7 | `horus-memgraph` image: rebuild on the same pinned base; shim packages included (already mostly true) | Image rebuilt and scanned | 1 | Todo |
| B8 | SBOM for every image (for example `syft`), attached at push | SBOMs published next to the images | 1 | Todo |
| B9 | `runtimes/build.sh` builds and pushes all images to any registry (`HORUS_REGISTRY`), with one version tag across the set | One command builds and pushes the set | 2 | Todo |
| B10 | Scan the set with JFrog Xray (or a stand-in such as Trivy until a JFrog instance is available); fix or waive each finding | Clean scan report saved | 3 | Todo |
| B11 | Egress-blocked install test: register the images, start every Application with outbound traffic blocked | All Applications reach running | 3 | Todo |
| B12 | Non-image artifacts for air-gapped delivery: basemap `.mbtiles`, Memgraph snapshot, NiFi flow JSON, OFAC snapshot; checksums and a manifest | Delivery bundle documented | 2 | Todo |
| B13 | INSTALL.md: image-based install path (registry, runtime registration, Application settings), alongside the current repo-based path | Section written and followed once | 2 | Todo |

## C. Identity and access

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| C1 | SSO in front of every Application (Knox or Workbench auth); drop unauthenticated access. Moved from BURNDOWN 6.5. | No Application opens without login | 6 | Todo |
| C2 | Per-user identity through to Trino and Ranger, instead of one shared workload login | Ranger audit shows the viewing user | 4 | Todo |
| C3 | Bearer token required on the MCP server's `/mcp`; Memgraph shim token passed through. Moved from BURNDOWN 3.2. | Unauthenticated call rejected | 1 | Todo |
| C4 | Service-to-service tokens between the UI, gateway, intel resolver and Memgraph shim | Direct calls without a token are rejected | 3 | Todo |

## D. Credentials and secrets

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| D1 | Remove the CDP access key from the Workbench project after provisioning. Moved from BURNDOWN C5. | Key deleted | 0.1 | Todo |
| D2 | Rotate the Kafka password committed in the OSIRIS repo. Moved from BURNDOWN C6. | Rotated; old value invalid | 0.5 | Todo |
| D3 | Secrets (workload password, Mistral key, aisstream key) held in one place with a rotation procedure | Procedure in INSTALL.md | 1 | Todo |
