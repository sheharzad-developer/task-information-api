# Troubleshooting

Organised by where the problem shows up. Each entry: **symptom → cause → fix**.

Jump to: [Local](#local-development) · [Docker](#docker) · [GitHub Actions — test/build](#github-actions--test-and-build) · [AWS credentials (OIDC)](#aws-credentials-oidc) · [ECR](#ecr) · [CloudFormation](#cloudformation) · [ECS and load balancer](#ecs-and-load-balancer) · [Restricted AWS accounts](#restricted-aws-accounts-no-iam-role-creation) · [Command cheat sheet](#command-cheat-sheet)

---

## Local development

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` when running pytest | Running from the wrong folder | Run from the project root (the folder containing `pyproject.toml`). |
| `ImportError: cannot import name 'UTC' from 'datetime'` or `StrEnum` | Python older than 3.11 | Install Python 3.12+ and recreate the venv. |
| `[Errno 48/98] Address already in use` | Something else is on port 8000 | `lsof -i :8000` (macOS/Linux) and stop it, or `uvicorn app.main:app --port 8001`. |
| `make: command not found` (Windows) | No make | Run the underlying commands from the `Makefile` directly, or use WSL/Git Bash. |
| Coverage below 90% fails the test run | New code without tests | Add tests. `pytest --cov --cov-report=term-missing` lists the uncovered lines. |
| `ruff format --check` fails | Code not formatted | `ruff format .` then commit. |

## Docker

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Start Docker Desktop; check with `docker info`. |
| Container exits immediately | Startup error | `docker logs task-api` (or run without `-d`) to see the traceback. |
| `curl: (7) Failed to connect to localhost port 8000` | Port not published, or container still starting | Use `-p 8000:8000`; wait a few seconds; check `docker ps`. |
| `docker ps` shows `(unhealthy)` | `/health` not answering inside the container | `docker inspect --format '{{json .State.Health}}' task-api` shows the health-check output. |
| Code changes don't appear | Old image | Rebuild: `docker build ...` or `docker compose up --build`. |
| Build very slow every time | Cache invalidated | Keep `COPY requirements.txt` before `COPY app`; check `.dockerignore` excludes `.venv`. |

## GitHub Actions — test and build

| Symptom | Cause | Fix |
|---|---|---|
| Deploy job shows **skipped** | `AWS_DEPLOY_ROLE_ARN` repository variable not set, or the run wasn't on `main` | Expected before AWS setup. Add the variable (step 8). It must be a **repository** variable, not an environment variable. |
| Deploy job waiting with "Waiting for review" | Required reviewers configured on the `production` environment | Approve it on the run page. |
| "Lint (ruff)" fails | Lint/format error | Run `make lint` locally; the annotations in the run point at the exact lines. |
| Smoke test fails: `grep -q "version":"..."` | `APP_VERSION` not passed into the image | Check the `build-args` line in the workflow and `ARG/ENV APP_VERSION` in the Dockerfile. |
| Smoke test fails: `test "$user" = "10001:10001"` | `USER` line in the Dockerfile changed | Restore `USER 10001:10001`. |
| Deploy job fails at "Download image artifact" (artifact not found) | The build job's upload step was skipped | The deploy job only works for pushes to `main`; check the build job's "Upload image artifact" step ran. |
| Workflow doesn't run at all | File not at `.github/workflows/ci-cd.yml`, or Actions disabled | Check the path; **Settings → Actions → General → Allow all actions**. |

## AWS credentials (OIDC)

| Symptom | Cause | Fix |
|---|---|---|
| `Could not load credentials from any providers` | Missing `id-token: write` permission | It's set on the deploy job; don't remove it. |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The role's trust policy doesn't match the token. Most often the GitHub org/repo name is mistyped (it's **case-sensitive**), the job isn't in the `production` environment, or you renamed the repo. | Re-deploy `01-bootstrap.yml` with the exact `GitHubOrg`/`GitHubRepo`. Confirm the job has `environment: production`. The expected subject is `repo:<org>/<repo>:environment:production`. |
| `No OpenIDConnect provider found in your account for https://token.actions.githubusercontent.com` | `CreateOidcProvider=false` but no provider exists | Re-deploy bootstrap with `CreateOidcProvider=true`. |
| `Request ARN is invalid` | `AWS_DEPLOY_ROLE_ARN` variable has spaces or the wrong value | Copy the `DeployRoleArn` output exactly. |
| `Input required and not supplied: aws-region` | `AWS_REGION` variable missing | Add it as a repository variable. |

## ECR

| Symptom | Cause | Fix |
|---|---|---|
| `denied: Your authorization token has expired` (manual push) | Docker login is valid for 12 h | Re-run the `aws ecr get-login-password ... docker login` command. |
| `name unknown: The repository with name 'task-api' does not exist` | Bootstrap stack not deployed, wrong region, or repo name differs | Check `aws ecr describe-repositories --region $AWS_REGION`; set the `ECR_REPOSITORY` variable if you used another name. |
| `tag invalid: The image tag 'xxx' already exists ... cannot be overwritten because the repository is immutable` | Pushing the same tag twice | The pipeline already skips existing tags. For manual pushes, use a new tag. |
| Push denied (`not authorized to perform: ecr:InitiateLayerUpload`) | Role's policy targets a different repository | Repo name and `AppName` must match between the stack and the workflow. |

## CloudFormation

| Symptom | Cause | Fix |
|---|---|---|
| `Requires capabilities : [CAPABILITY_NAMED_IAM]` | Flag missing | Add `--capabilities CAPABILITY_NAMED_IAM`. |
| `Provider with url https://token.actions.githubusercontent.com already exists` | Account already has a GitHub OIDC provider | Deploy with `CreateOidcProvider=false`. |
| `Stack is in ROLLBACK_COMPLETE state and can not be updated` | The first create failed | Read why: `aws cloudformation describe-stack-events --stack-name <name> --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table`, fix it, then `delete-stack` and deploy again. |
| `task-api-ecs-execution-role already exists` | A previous stack/role with that name survived | Delete the old role or stack, or use a different `AppName` (and set the matching GitHub variables). |
| App stack stuck on `CREATE_IN_PROGRESS` for `Service` for 10+ minutes | The ECS task keeps failing, so the service never stabilises | See [ECS and load balancer](#ecs-and-load-balancer); fix the task, and the stack will finish or roll back after ~3 h — delete it to stop sooner. |
| `Unable to assume the service linked role` creating the service | First ECS use in this account | `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`, then delete and recreate the stack. |
| After updating `02-app.yml`, the site went back to an old version | The stack's `ImageUri` parameter is older than what the pipeline deployed | Always pass the currently running image when updating the stack — see "Changing the infrastructure later" in DEPLOYMENT.md. |

## ECS and load balancer

First, see what ECS says:

```bash
aws ecs describe-services --cluster task-api-cluster --services task-api-service \
  --query "services[0].events[0:8].message" --output table

# Why did the last task stop?
TASK=$(aws ecs list-tasks --cluster task-api-cluster --desired-status STOPPED --query "taskArns[0]" --output text)
aws ecs describe-tasks --cluster task-api-cluster --tasks $TASK \
  --query "tasks[0].{reason:stoppedReason,container:containers[0].reason,exit:containers[0].exitCode}"
```

| Symptom | Cause | Fix |
|---|---|---|
| ALB returns **503 Service Temporarily Unavailable** | No healthy targets: task still starting, or failing | Wait 60 s after deploy. If it persists, check service events and the target health command below. |
| ALB returns **502 Bad Gateway** | Container crashed or isn't listening on 8000 | Check logs: `aws logs tail /ecs/task-api --since 15m`. |
| Stopped reason: `CannotPullContainerError ... not found` | Image tag doesn't exist in ECR | Push it (step 6) or fix `ImageUri`. |
| Stopped reason: `CannotPullContainerError ... i/o timeout` | Task has no route to ECR | Tasks must be in the public subnets with `AssignPublicIp: ENABLED` (the template does this). If you moved them to private subnets, add a NAT gateway or VPC endpoints. |
| Log shows `exec format error` | Image built for ARM (Apple Silicon) but Fargate runs x86_64 | Rebuild with `docker build --platform linux/amd64 ...`. The CI pipeline always builds x86_64. |
| Log shows `Read-only file system` | Something tries to write to disk; the root filesystem is read-only on ECS | Write to a mounted volume, or remove `ReadonlyRootFilesystem: true` from the task definition. |
| Targets `unhealthy` with `Health checks failed with these codes: [404]` | Health check path wrong | Target group must check `/health`. |
| Targets `unhealthy` with `Request timed out` | Security group blocks ALB → task | The service security group must allow port 8000 **from the ALB security group**. |
| Pipeline step "Deploy to ECS" times out or fails | New task never got healthy → circuit breaker rolled back | Production is still on the old version. Read the service events and logs above, fix, push again. |
| Smoke test: `/health never reported version <sha>` | Old task still serving, or deploy rolled back | Check `aws ecs describe-services ... deployments`; check the target group's health. |
| Tasks created via the API disappear | In-memory store: every deploy or restart starts a new, empty container | Expected for this assignment. Use DynamoDB/RDS for persistence (see ARCHITECTURE.md). |
| Data differs between requests | `DesiredCount` > 1 with in-memory storage — each task has its own data | Keep `DesiredCount=1` until storage is external. |

Target health:

```bash
TG=$(aws elbv2 describe-target-groups --names task-api-tg --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 describe-target-health --target-group-arn $TG \
  --query "TargetHealthDescriptions[].{ip:Target.Id,state:TargetHealth.State,reason:TargetHealth.Description}" --output table
```

## Restricted AWS accounts (no IAM role creation)

Some sandbox or lab accounts (for example AWS Academy Learner Lab) don't allow
creating IAM roles or OIDC providers, so `01-bootstrap.yml` fails with `AccessDenied`. Work-around:

1. Create the ECR repo by hand: `aws ecr create-repository --repository-name task-api --image-scanning-configuration scanOnPush=true`.
2. In `02-app.yml`, remove the `TaskExecutionRole` and `TaskRole` resources and set both `ExecutionRoleArn` and `TaskRoleArn` to the pre-made role (e.g. `arn:aws:iam::<account>:role/LabRole`).
3. Store the lab's temporary credentials as GitHub **secrets** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and in the workflow replace `role-to-assume` with:
   ```yaml
   aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
   aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
   aws-session-token: ${{ secrets.AWS_SESSION_TOKEN }}
   ```
   and change the deploy job's condition from `vars.AWS_DEPLOY_ROLE_ARN != ''` to `vars.AWS_REGION != ''`.
4. Lab credentials expire every few hours; update the secrets before each deploy.

Use OIDC whenever the account allows it — stored keys are the less secure option.

## Command cheat sheet

```bash
# Who am I / which account?
aws sts get-caller-identity

# Stack status and outputs
aws cloudformation describe-stacks --stack-name task-api-app --query "Stacks[0].[StackStatus,Outputs]"

# Live logs
aws logs tail /ecs/task-api --follow

# Service, running tasks, current image
aws ecs describe-services --cluster task-api-cluster --services task-api-service \
  --query "services[0].{running:runningCount,taskDef:taskDefinition,state:deployments[0].rolloutState}"
aws ecs describe-task-definition --task-definition task-api --query "taskDefinition.containerDefinitions[0].image"

# Force a restart of the same version
aws ecs update-service --cluster task-api-cluster --service task-api-service --force-new-deployment

# Images in ECR and their scan results
aws ecr describe-images --repository-name task-api --query "imageDetails[].[imageTags[0],imagePushedAt,imageScanFindingsSummary.findingSeverityCounts]"
```
