# Deployment guide — step by step

This takes the project from your laptop to a live URL on AWS, with every later
change deployed automatically by GitHub Actions.

| Step | What you do | Result |
|---|---|---|
| 1 | Run and test locally | API on `localhost:8000` |
| 2 | Build and run the Docker image | Same API, in a container |
| 3 | Push to GitHub | CI runs tests and builds the image |
| 4 | Set up your AWS shell | Variables used by every later command |
| 5 | Deploy the bootstrap stack | ECR repository + deploy role for GitHub |
| 6 | Push the first image by hand | ECR holds an image the service can start from |
| 7 | Deploy the application stack | Live URL on AWS |
| 8 | Connect GitHub to AWS | Pipeline allowed to deploy |
| 9 | Trigger the first automated deploy | Push → live in ~5 minutes |
| 10 | Verify, observe, roll back | Logs, metrics, recovery |
| 11 | Tear down | No ongoing charges |

Commands are written for bash (macOS, Linux, WSL, or Git Bash on Windows).

---

## Prerequisites

| Tool | Check | Notes |
|---|---|---|
| Python 3.12+ | `python --version` | |
| Docker | `docker version` | Docker Desktop on macOS/Windows |
| Git + a GitHub account | `git --version` | |
| AWS CLI v2 | `aws --version` | |
| AWS credentials | `aws sts get-caller-identity` | Must print your account ID. Needs rights to create IAM roles, VPCs, ECS and ECR resources (an admin user is simplest for this assignment). |
| GitHub CLI (optional) | `gh --version` | Only makes step 8 faster |

---

## Step 1 — Run and test locally

```bash
cd task-api
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

make lint                          # ruff: lint + formatting
make test                          # pytest with coverage (fails under 90%)
make run                           # uvicorn with auto-reload
```

Open <http://localhost:8000/docs> and try each endpoint from Swagger UI, or:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/v1/tasks -H "Content-Type: application/json" -d '{"title":"First task"}'
curl http://localhost:8000/api/v1/tasks
```

No `make`? Run the commands it wraps: `ruff check . && ruff format --check .`,
`pytest --cov`, `uvicorn app.main:app --reload`.

---

## Step 2 — Build and run the Docker image

```bash
docker build --build-arg APP_VERSION=local -t task-api:local .
docker run --rm -p 8000:8000 --name task-api task-api:local
```

In a second terminal:

```bash
curl http://localhost:8000/health          # "version":"local"
docker ps                                   # STATUS shows "(healthy)" after ~10 s
docker inspect --format '{{.Config.User}}' task-api:local   # 10001:10001, not root
docker image ls task-api                    # small slim-based image, no build tools
```

Or with Compose: `docker compose up --build`, stop with `Ctrl+C` then `docker compose down`.

What the Dockerfile does:

- **Two stages.** Dependencies are installed into a virtualenv in a builder stage; only that venv and the `app/` folder are copied into the final image. Build tools and the pip cache never reach production.
- **Layer caching.** `requirements.txt` is copied before the code, so changing code doesn't reinstall dependencies.
- **Non-root.** Runs as UID 10001.
- **Health check.** Calls `/health` with Python's standard library (the slim image has no `curl`).
- **Graceful shutdown.** `exec` makes uvicorn PID 1, so it receives ECS's `SIGTERM` and finishes in-flight requests.

---

## Step 3 — Push to GitHub

Create an **empty** repository on GitHub (no README), then:

```bash
git init
git add .
git commit -m "Task API with CI/CD pipeline"
git branch -M main
git remote add origin https://github.com/<your-user>/task-api.git
git push -u origin main
```

Open the **Actions** tab. The `CI/CD` workflow runs:

1. **Lint & test** — ruff, then pytest; coverage and JUnit reports are uploaded as artifacts.
2. **Build & smoke-test image** — builds the image, starts it, checks `/health`, creates a task (expects 201), sends bad input (expects 422), and confirms it isn't running as root.
3. **Push to ECR & deploy to ECS** — *skipped* for now, because `AWS_DEPLOY_ROLE_ARN` isn't set yet. The pipeline stays green until AWS exists.

On a pull request only jobs 1 and 2 run; nothing is pushed or deployed.

> Recommended: **Settings → Branches → Add rule** for `main`, require the "Lint & test" and "Build & smoke-test image" checks to pass before merging. That turns the pipeline into a real quality gate.

---

## Step 4 — Set up your AWS shell

Pick a region and set these once per terminal session. Every later command uses them.

```bash
export AWS_REGION=us-east-1                 # or ap-south-1, me-central-1, eu-west-1, ...
export APP_NAME=task-api                    # keep this unless you also change the workflow defaults
export GH_ORG=<your-github-user-or-org>
export GH_REPO=task-api
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGISTRY=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
export ECR_URI=$REGISTRY/$APP_NAME

echo "$ACCOUNT_ID  $AWS_REGION  $ECR_URI"
```

---

## Step 5 — Deploy the bootstrap stack (ECR + GitHub deploy role)

An AWS account can hold only **one** GitHub OIDC provider. Check whether one already exists:

```bash
aws iam list-open-id-connect-providers | grep token.actions.githubusercontent.com \
  && echo "EXISTS: add CreateOidcProvider=false below" || echo "Not found: use the default"
```

Deploy:

```bash
aws cloudformation deploy \
  --region $AWS_REGION \
  --stack-name $APP_NAME-bootstrap \
  --template-file infra/cloudformation/01-bootstrap.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides AppName=$APP_NAME GitHubOrg=$GH_ORG GitHubRepo=$GH_REPO
  # add:  CreateOidcProvider=false   if the check above said EXISTS
```

This creates:

| Resource | Purpose |
|---|---|
| ECR repository `task-api` | Private image registry. Tags are **immutable** (a commit SHA always means one image), images are **scanned for CVEs on push**, only the newest 15 are kept. |
| IAM OIDC provider | Lets AWS trust short-lived tokens issued by GitHub Actions. |
| IAM role `task-api-github-deploy` | What the pipeline assumes. It can push to *this* repository and update *this* ECS service — nothing else — and only jobs running in your repo's `production` environment can assume it. |

Print the outputs (you need `DeployRoleArn` in step 8):

```bash
aws cloudformation describe-stacks --region $AWS_REGION --stack-name $APP_NAME-bootstrap \
  --query "Stacks[0].Outputs" --output table
```

---

## Step 6 — Push the first image by hand

The ECS service in step 7 needs an image to start from. After this, the pipeline handles every push.

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $REGISTRY

# --platform matters on Apple Silicon (M1/M2/M3): Fargate is set to x86_64.
docker build --platform linux/amd64 --build-arg APP_VERSION=initial -t $ECR_URI:initial .
docker push $ECR_URI:initial
```

Confirm, and check the vulnerability scan:

```bash
aws ecr describe-images --region $AWS_REGION --repository-name $APP_NAME --output table
aws ecr describe-image-scan-findings --region $AWS_REGION --repository-name $APP_NAME \
  --image-id imageTag=initial --query "imageScanFindings.findingSeverityCounts"
```

---

## Step 7 — Deploy the application stack

```bash
aws cloudformation deploy \
  --region $AWS_REGION \
  --stack-name $APP_NAME-app \
  --template-file infra/cloudformation/02-app.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides AppName=$APP_NAME ImageUri=$ECR_URI:initial
```

This takes about 5 minutes. It creates a VPC across two availability zones, an
Application Load Balancer, an ECS cluster, a Fargate service running one task,
and a CloudWatch log group. (Optional HTTPS: add `CertificateArn=<ACM cert ARN in the same region>`.)

Get the URL and test it:

```bash
export APP_URL=$(aws cloudformation describe-stacks --region $AWS_REGION --stack-name $APP_NAME-app \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)
echo $APP_URL

curl $APP_URL/health        # "version":"initial", "environment":"production"
```

If you get `503`, the task is still starting — wait 30–60 seconds. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#ecs-and-load-balancer) if it persists.

---

## Step 8 — Connect GitHub to AWS

### 8a. Create the environment

**GitHub → your repo → Settings → Environments → New environment** → name it exactly `production`.

Optional but worth showing: tick **Required reviewers** and add yourself. Every deploy then pauses for a manual approval — a common production gate.

### 8b. Add repository variables

**Settings → Secrets and variables → Actions → Variables tab → New repository variable.**
Add them as **repository** variables (not environment variables): the deploy job's
`if:` condition is evaluated before the environment is entered, so it cannot see
environment-level variables.

| Name | Value | Where to find it |
|---|---|---|
| `AWS_REGION` | e.g. `us-east-1` | Step 4 |
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::<account>:role/task-api-github-deploy` | Step 5 output `DeployRoleArn` |
| `APP_URL` | `http://task-api-alb-....elb.amazonaws.com` (no trailing slash) | Step 7 output `AppUrl` |

These are **variables, not secrets**: none of them is sensitive. There are no AWS
access keys anywhere — GitHub gets temporary credentials from AWS through OIDC on
each run, and they expire within an hour.

With the GitHub CLI instead:

```bash
DEPLOY_ROLE_ARN=$(aws cloudformation describe-stacks --region $AWS_REGION --stack-name $APP_NAME-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text)

gh variable set AWS_REGION          --body "$AWS_REGION"
gh variable set AWS_DEPLOY_ROLE_ARN --body "$DEPLOY_ROLE_ARN"
gh variable set APP_URL             --body "$APP_URL"
```

Optional overrides (only if you changed names in the templates): `ECR_REPOSITORY`,
`ECS_CLUSTER`, `ECS_SERVICE`, `ECS_TASK_FAMILY`, `ECS_CONTAINER_NAME`.

---

## Step 9 — Trigger the first automated deploy

Make any change and push it to `main`:

```bash
git commit --allow-empty -m "Trigger first automated deployment"
git push
```

(Or **Actions → CI/CD → Run workflow**.)

The deploy job now runs:

1. Downloads the image the build job already tested (it is **not rebuilt**, so what was tested is exactly what ships).
2. Gets temporary AWS credentials via OIDC.
3. Pushes the image to ECR tagged with the 12-character commit SHA.
4. Reads the current ECS task definition, swaps in the new image and `APP_VERSION`, registers a new revision.
5. Updates the ECS service and **waits** until the new task passes its health checks and the old one has drained. If the new version never becomes healthy, ECS's circuit breaker rolls back automatically and this step fails.
6. Polls `$APP_URL/health` until it reports the new commit SHA.

The run summary shows the image URI and deployed version. Then:

```bash
curl $APP_URL/health      # "version" now equals the first 12 characters of your commit SHA
```

From here on: **merge to `main` → live in about 5 minutes.**

---

## Step 10 — Verify, observe, roll back

### Exercise the live API

```bash
curl -X POST $APP_URL/api/v1/tasks -H "Content-Type: application/json" \
  -d '{"title":"Deployed on AWS","priority":"high"}'
curl "$APP_URL/api/v1/tasks?priority=high"
open $APP_URL/docs         # Linux: xdg-open
```

### Logs

```bash
aws logs tail /ecs/$APP_NAME --region $AWS_REGION --follow
```

Logs are one JSON object per line. Find all errors in **CloudWatch → Logs Insights** (log group `/ecs/task-api`):

```
fields @timestamp, level, status, path, request_id, message
| filter level = "ERROR" or status >= 500
| sort @timestamp desc
```

To trace a request a user reported, filter by the `X-Request-ID` value from the response header: `| filter request_id = "..."`.

### Service state

```bash
aws ecs describe-services --region $AWS_REGION --cluster $APP_NAME-cluster --services $APP_NAME-service \
  --query "services[0].{running:runningCount,desired:desiredCount,taskDef:taskDefinition,rollout:deployments[0].rolloutState,events:events[0:5].message}"
```

CPU and memory graphs: **ECS console → Clusters → task-api-cluster → Services → task-api-service → Health and metrics** (Container Insights is enabled).

### Roll back

| Situation | What to do |
|---|---|
| New version fails health checks | Nothing — the ECS circuit breaker rolls back by itself and the pipeline run fails. |
| New version is healthy but wrong | **Best:** `git revert` the bad commit and push; the pipeline deploys the fix. |
| Need the old version *now* | **Actions** → open the last good run → **Re-run jobs → deploy**. Its image is still in ECR, so it is redeployed in a couple of minutes. |
| Directly via CLI | `aws ecs update-service --cluster $APP_NAME-cluster --service $APP_NAME-service --task-definition $APP_NAME:<previous revision>` (list revisions with `aws ecs list-task-definitions --family-prefix $APP_NAME`) |

### Changing the infrastructure later

The pipeline registers new task definition revisions that CloudFormation doesn't
know about. When you re-deploy `02-app.yml`, pass the image that is **currently
live**, or the stack update will roll the service back to the old image:

```bash
CURRENT_IMAGE=$(aws ecs describe-task-definition --region $AWS_REGION --task-definition $APP_NAME \
  --query "taskDefinition.containerDefinitions[0].image" --output text)

aws cloudformation deploy --region $AWS_REGION --stack-name $APP_NAME-app \
  --template-file infra/cloudformation/02-app.yml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides AppName=$APP_NAME ImageUri=$CURRENT_IMAGE
```

---

## Step 11 — Tear down

Running cost is roughly **USD 30–35/month** (load balancer ≈ 16–18, one 0.25 vCPU / 0.5 GB Fargate task ≈ 9, public IPv4 addresses ≈ 7, plus small amounts for logs and ECR storage). Delete everything once the assignment is graded:

```bash
aws cloudformation delete-stack --region $AWS_REGION --stack-name $APP_NAME-app
aws cloudformation wait stack-delete-complete --region $AWS_REGION --stack-name $APP_NAME-app

# Deletes the ECR repository and all its images, the deploy role and the OIDC provider
aws cloudformation delete-stack --region $AWS_REGION --stack-name $APP_NAME-bootstrap
aws cloudformation wait stack-delete-complete --region $AWS_REGION --stack-name $APP_NAME-bootstrap
```

Then delete the `AWS_DEPLOY_ROLE_ARN` variable in GitHub (or the deploy job will run and fail).

> If you used `CreateOidcProvider=false`, the shared OIDC provider was not created by this stack and is left in place, which is what you want.
