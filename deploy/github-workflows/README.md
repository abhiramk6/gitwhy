# CI/CD workflows (inactive until activated)

`ci.yml` (tests, frontend build, secret scan, Docker build) and `deploy.yml` (Cloud Run deploy, a no-op until the
`GCP_*` repository variables exist) are kept here because the token used to push this repository has no `workflow`
scope, and GitHub refuses pushes that create files under `.github/workflows/`.

To activate: add the `workflow` scope to the token (or add the files in the GitHub web editor), then

    git mv deploy/github-workflows/ci.yml deploy/github-workflows/deploy.yml .github/workflows/

`.github/dependabot.yml` is already active.
