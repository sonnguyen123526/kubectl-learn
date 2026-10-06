# kubectl-learn

Learn kubectl by doing real tasks on a real kind cluster.

kubectl-learn is a command-line tutor for Kubernetes. It gives you a task
("run a redis pod in a new namespace"), you do it with plain `kubectl` in your
own terminal, and it checks the cluster to tell you whether you got it right,
and if not, exactly what's wrong. It records every attempt, reports your
mastery of each concept, and picks your next task based on what you're
weakest at.

```
$ kubectl-learn start
Task: Work in a namespace  (concept: namespaces, difficulty: 2/3)
Picked because you haven't tried namespaces yet (14% chance this time).

Create a namespace named team-a. Then, inside team-a, run a pod named cache
that uses the redis image.

$ kubectl run cache --image=redis
$ kubectl-learn check
FAIL: Pod 'cache' is in the default namespace, and there's no namespace
'team-a' yet. Create the namespace, then run the pod inside it.
```

## Install

You need:

- [Docker](https://docs.docker.com/get-docker/), which kind uses to run the cluster
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) and
  [kubectl](https://kubernetes.io/docs/tasks/tools/) (on macOS: `brew install kind kubectl`)
- Python 3.8 or newer, with PyYAML

1. Create a cluster to practice on:

   ```bash
   kind create cluster --name learn
   kubectl config current-context    # should print kind-learn
   ```

2. Install the one Python dependency:

   ```bash
   python3 -m pip install pyyaml
   ```

3. Make the `kubectl-learn` command available. Either add an alias to your
   `~/.zshrc` or `~/.bashrc`:

   ```bash
   alias kubectl-learn="python3 /path/to/kubectl-learn/learn.py"
   ```

   or link the script into a directory on your `PATH`:

   ```bash
   chmod +x learn.py
   mkdir -p ~/.local/bin
   ln -s "$PWD/learn.py" ~/.local/bin/kubectl-learn
   # if ~/.local/bin isn't on your PATH yet, add this to ~/.zshrc:
   # export PATH="$HOME/.local/bin:$PATH"
   ```

   With the link, `kubectl learn start` works too: kubectl treats any program
   named `kubectl-<something>` on your `PATH` as a plugin.

> **Use a cluster you don't mind losing things on.** kubectl-learn works on
> whatever cluster `kubectl` currently points at. `start` and `reset` delete
> resources the tasks use, by name: for example the pod `web`, the deployments
> `api`, `cart`, `shop` and `frontend`, and the namespace `team-a`. A dedicated
> kind cluster is the safe choice.

## Usage

| Command | What it does |
|---|---|
| `kubectl-learn start` | Pick a task (weighted toward your weak concepts), prepare the cluster for it, and show it. If you haven't finished your current task, show that one again. |
| `kubectl-learn start <task-id>` | Start a specific task instead, e.g. `start pod-web`. |
| `kubectl-learn hint` | Show a hint for the current task. Hints are recorded. |
| `kubectl-learn check` | Check your work against the cluster: **PASS**, **FAIL** (with what's wrong), or **NOT YET** (looks right, Kubernetes is still catching up). |
| `kubectl-learn report` | Show attempts, pass rate, mastery per concept, time, hints, and your weakest concepts. |
| `kubectl-learn reset` | Delete everything the tasks created. If a task is in progress, recreate its starting point so you can retry it. |

A session looks like this:

```bash
kubectl-learn start        # read the task
kubectl get pods           # ...work on it with kubectl...
kubectl-learn check        # FAIL: tells you what's wrong
kubectl-learn hint         # if you're stuck
kubectl-learn check        # PASS, with your time, hints and failed checks
kubectl-learn report       # see how you're doing
kubectl-learn start        # next task
```

Presenting the project? [docs/demo.md](docs/demo.md) is a 5-minute demo script.

### The tasks

| Task id | Concept | Difficulty | What you do |
|---|---|---|---|
| `pod-web` | pods | 1 | Run a pod with the nginx image |
| `deploy-api` | deployments | 1 | Create a deployment with an image, replica count and port |
| `scale-cart` | scaling | 1 | Scale an existing deployment from 1 to 4 pods |
| `label-select` | labels | 2 | Label exactly the pods that match a selector |
| `ns-cache` | namespaces | 2 | Create a namespace and run a pod inside it |
| `rollout-shop` | rollouts | 2 | Create a deployment, then roll it out to a new image |
| `configmap-env` | configmaps | 3 | Load a configmap into a pod's environment |
| `debug-frontend` | debugging | 3 | Find out why a deployment's pods crash, and fix it |

## How it works

```
 tasks/*.yaml ──► learn.py ──► verifiers/checks.py ──► kube.py ──► kubectl ──► cluster
 (what to do)     (the CLI)    (did it work?)          (runs kubectl, parses JSON)
                     │
                     ├──► progress.py ──► data/progress.json   (every attempt)
                     └──► report.py                            (mastery, weakest concepts)
```

| File | Role |
|---|---|
| `learn.py` | The command-line interface: `start`, `hint`, `check`, `report`, `reset`. Loads tasks and chooses the next one. |
| `tasks/*.yaml` | One file per task. Tasks are data, so adding one doesn't mean changing the program. |
| `verifiers/checks.py` | One `check_<name>` function per task. It inspects the cluster and returns pass/fail plus a message. |
| `kube.py` | Runs `kubectl` with `subprocess` and parses its `-o json` output. |
| `progress.py` | Records attempts in `data/progress.json`. |
| `report.py` | Calculates mastery and prints the report. |
| `data/` | Your state: `current.json` (the task you're on) and `progress.json` (your history). |

### A task file

```yaml
id: ns-cache                  # stable id, used in your history
title: Work in a namespace
prompt: >
  Create a namespace named team-a. Then, inside team-a, run a pod named cache
  that uses the redis image.
difficulty: 2                 # 1-3
concept: namespaces           # what the report groups by
hint: >
  `kubectl create namespace <name>` makes a namespace. ...
verifier: check_ns_cache      # function name in verifiers/checks.py
cleanup:                      # optional: delete everything the task uses
  - [delete, namespace, team-a, --ignore-not-found]
  - [delete, pod, cache, --ignore-not-found, --now]
```

A task can also have a `setup` list that creates its starting point. For
example, `scale-cart` creates the deployment you'll scale. `start` runs
`cleanup` and then `setup` before showing the task. It prints the cleanup
commands but not the setup ones, which would give away the debugging task.

`check` reads the `verifier` name from the task and looks the function up
with `getattr(checks, name)`. To add a task, write a YAML file in `tasks/`
and a matching `check_` function in `verifiers/checks.py`.

A verifier asks kubectl for JSON (`kubectl get ... -o json`), not the table
you normally see. The table's columns change between versions and hide most
fields, while the JSON is the full object in a fixed structure. For example,
`pod["status"]["phase"]` always means the same thing.

## How this tool models learning

kubectl-learn is built on four ideas from learning research: you learn by
doing, you learn faster with immediate and specific feedback, practice should
focus on what you don't know yet, and progress should be measured rather than
guessed.

### Practice

Every task is real work on a real cluster. There are no multiple-choice
questions and no simulated terminal: you type the same `kubectl` commands you
would at work, and the task passes only if the cluster ends up in the right
state. Having to work out a command yourself (retrieval practice) builds much
stronger memory than reading or recognizing the answer.

Each task resets the cluster to its own starting point, so tasks can be done
in any order, and repeated, without leftovers from earlier attempts.

### Immediate feedback

`check` gives an answer in about a second, and the answer is specific. It
points at the gap between what's there and what should be, without giving
away the command:

- **It says what's wrong:** "Pod 'web' exists but its image is 'busybox',
  expected 'nginx'."
- **It shows what's there:** "Pod 'web' has no 'tier' label. Its labels are:
  Tier=front, run=web." That's enough for you to spot the capital T yourself.
- **It separates "not yet" from "wrong":** a container that's still starting
  gets `NOT YET`, not `FAIL`, so you don't "fix" work that was right. It
  isn't counted against you either.
- **It separates your mistakes from broken infrastructure:** if kubectl can't
  reach the cluster, `check` reports an ERROR, not a FAIL.
- **It recognizes partial progress:** "Deployment 'shop' is still on
  nginx:1.25. Now update it to nginx:1.27."

Hints are available, but you have to ask for them, and asking is recorded.

### Adaptive repetition

`start` doesn't go through tasks in a fixed order. It draws one at random,
weighted toward the concepts you're weakest in:

```
weight = 0.1 + 0.9 × (1 − mastery)
```

A concept you've never tried, or scored 0% on, has weight 1.0. At 70% it's
0.37, and once mastered it's 0.1. So weak concepts come up most of the time,
and mastered ones still return now and then for review, about ten times less
often. The task you just did is never picked straight away, because practice
sticks better after a gap. `start` tells you why it picked a task and what
chance it had.

This is the core idea of spaced repetition (as in flashcard apps): spend
practice where it does the most good, and keep reviewing what you know so
you don't forget it. Mixing concepts at random, rather than doing them one
block at a time ("interleaving"), also makes you work out which tool a
problem needs, which is the skill you need on a real cluster.

The loop corrects itself: practicing a weak concept raises its mastery,
which lowers its weight, which moves practice on to the next weakest one.

### Measured progress

Every attempt is stored in `data/progress.json`:

```json
{"task_id": "ns-cache", "concept": "namespaces",
 "started_at": "2026-10-05T20:41:07-04:00",
 "passed": true, "seconds": 192, "hints": 1, "failed_checks": 1}
```

Pass/fail alone says little, because you can keep trying until you pass.
Time, hints and failed checks show how you passed: on your own and quickly,
or with help after several wrong attempts. The report turns this into a
mastery score per concept:

| Outcome of an attempt | Score |
|---|---|
| Not passed (yet) | 0 |
| Passed | 100 |
| ...minus, if you used the hint | −30 |
| ...minus, per failed check (at most 3) | −10 each |

A concept's mastery is the average score of its attempts. The weights are
named constants at the top of `report.py`, and the report is recalculated
from the raw history every time, so anyone can check the numbers by hand.

```
  Concept      Mastery            Attempts    Avg time  Hints
  pods         [##########] 100%  1 attempt     1m 35s  0
  labels       [#######---]  70%  1 attempt     2m 20s  2
  rollouts     [####------]  40%  1 attempt    10m 10s  1
```

### Limitations

- **The history is a plain file on your machine.** It's a learning log, not
  a tamper-proof exam record.
- **Verifiers check the end state, not how you got there.** They can't tell
  a command you worked out from one you copied.
- **Time is wall-clock time from `start` to the passing check,** so it
  includes breaks.
- **Mastery weights all attempts equally,** so early struggles still count
  after you've improved.
- **Task selection ignores difficulty,** so a beginner can be given a
  difficulty-3 task first.
