# kubectl-learn

Learn kubectl by doing real tasks on a real kind cluster.

I built this because reading the Kubernetes docs never made kubectl stick for
me. I'd read about namespaces, nod along, and then forget `-n` the first time
I actually needed it. What helped was typing commands against a real cluster,
messing up, and figuring out why. So this tool turns that into a loop: it
gives you a task, you do it with plain `kubectl` in your own terminal, and it
checks the cluster and tells you what you got wrong. It also keeps track of
how each attempt went and uses that to decide what you should practice next.

Here's what a round looks like:

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

(Yes, I forgot `-n`. That's exactly the kind of mistake it's built to catch.)

## Getting it running

You'll need:

- [Docker](https://docs.docker.com/get-docker/), since kind runs the cluster inside it
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) and
  [kubectl](https://kubernetes.io/docs/tasks/tools/) (on a Mac: `brew install kind kubectl`)
- Python 3.8 or newer, plus PyYAML

1. Make a cluster to practice on:

   ```bash
   kind create cluster --name learn
   kubectl config current-context    # should print kind-learn
   ```

2. Install the one Python dependency:

   ```bash
   python3 -m pip install pyyaml
   ```

3. Make `kubectl-learn` a command you can type. The quick way is an alias in
   your `~/.zshrc` or `~/.bashrc`:

   ```bash
   alias kubectl-learn="python3 /path/to/kubectl-learn/learn.py"
   ```

   Or link the script onto your `PATH`:

   ```bash
   chmod +x learn.py
   mkdir -p ~/.local/bin
   ln -s "$PWD/learn.py" ~/.local/bin/kubectl-learn
   # if ~/.local/bin isn't on your PATH yet, add this to ~/.zshrc:
   # export PATH="$HOME/.local/bin:$PATH"
   ```

   A fun side effect of the second option: `kubectl learn start` works too.
   kubectl treats any program named `kubectl-<something>` on your `PATH` as a
   plugin, so the tool shows up as a kubectl subcommand.

> **Heads up: use a cluster you don't care about.** kubectl-learn runs against
> whatever cluster `kubectl` is currently pointed at, and `start` and `reset`
> delete the resources the tasks use, by name (the pod `web`, the deployments
> `api`, `cart`, `shop` and `frontend`, the namespace `team-a`, and so on). On
> a throwaway kind cluster that's exactly what you want. On a real one, it
> really isn't.

## Using it

| Command | What it does |
|---|---|
| `kubectl-learn start` | Picks a task for you (leaning toward your weak spots), resets the cluster for it, and shows it. If you haven't finished your current task, it just shows that one again. |
| `kubectl-learn start <task-id>` | Starts a specific task, like `start pod-web`. Handy for demos or drilling one thing. |
| `kubectl-learn hint` | Shows a hint for the current task. Fair warning: it gets recorded. |
| `kubectl-learn check` | Checks your work against the cluster. You'll get **PASS**, **FAIL** (with what's wrong), or **NOT YET** (looks right, Kubernetes just hasn't caught up). |
| `kubectl-learn report` | Shows your attempts, pass rate, mastery per concept, time, hints, and your two weakest concepts. |
| `kubectl-learn reset` | Deletes everything the tasks created. If you're in the middle of a task, it puts that task's starting point back so you can try again. |

In practice a session goes something like this:

```bash
kubectl-learn start        # read the task
kubectl get pods           # ...poke around and work on it...
kubectl-learn check        # FAIL: here's what's wrong
kubectl-learn hint         # if you're stuck
kubectl-learn check        # PASS, plus your time, hints and failed checks
kubectl-learn report       # how am I doing overall?
kubectl-learn start        # on to the next one
```

### The tasks

There are eight so far, one for each concept I wanted to cover, roughly
easiest to hardest:

| Task id | Concept | Difficulty | What you do |
|---|---|---|---|
| `pod-web` | pods | 1 | Run a pod with the nginx image |
| `deploy-api` | deployments | 1 | Create a deployment with an image, replica count and port |
| `scale-cart` | scaling | 1 | Scale an existing deployment from 1 to 4 pods |
| `label-select` | labels | 2 | Label exactly the pods that match a selector |
| `ns-cache` | namespaces | 2 | Create a namespace and run a pod inside it |
| `rollout-shop` | rollouts | 2 | Create a deployment, then roll it out to a new image |
| `configmap-env` | configmaps | 3 | Load a configmap into a pod's environment |
| `debug-frontend` | debugging | 3 | Figure out why a deployment's pods keep crashing, and fix it |

My favorite is `debug-frontend`. The pods are broken on purpose, and the check
won't tell you why. You have to go find out with `kubectl get`, `describe` and
`logs`, the same way you would if it broke for real.

## How it's put together

```
 tasks/*.yaml ──► learn.py ──► verifiers/checks.py ──► kube.py ──► kubectl ──► cluster
 (what to do)     (the CLI)    (did it work?)          (runs kubectl, parses JSON)
                     │
                     ├──► progress.py ──► data/progress.json   (every attempt)
                     └──► report.py                            (mastery, weakest concepts)
```

| File | What it's for |
|---|---|
| `learn.py` | The command-line part: `start`, `hint`, `check`, `report`, `reset`. It also loads the tasks and picks the next one. |
| `tasks/*.yaml` | One file per task. |
| `verifiers/checks.py` | One `check_<name>` function per task. Each looks at the cluster and returns pass/fail plus a message. |
| `kube.py` | Runs `kubectl` with `subprocess` and parses its `-o json` output. |
| `progress.py` | Writes every attempt to `data/progress.json`. |
| `report.py` | Works out mastery and prints the report. |
| `data/` | Your personal state: `current.json` (the task you're on) and `progress.json` (your history). It's in `.gitignore`. |

### Tasks are just data

Early on I decided tasks should be YAML files, not code. Adding a task then
means writing a file, not touching the program, and everything that runs the
tasks stays generic. It doesn't know or care what a pod is. A task looks like
this:

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

A task can also have a `setup` list that builds its starting point. For
example, `scale-cart` creates the deployment you're supposed to scale.
`start` runs `cleanup`, then `setup`, and only then shows you the task. It
prints the cleanup commands, so you can see what it deleted, but not the
setup ones, because that would spoil the debugging task.

The only part that has to be real code is the checking. The task file just
names its verifier, and `check` looks the function up at runtime with
`getattr(checks, name)`. So adding a task is two steps: a YAML file in
`tasks/`, and a matching `check_` function in `verifiers/checks.py`.

### Why the verifiers ask for JSON

Verifiers never read the table you normally see from `kubectl get`. They ask
for `-o json`. The table is meant for people: its columns change between
versions and it hides most of the fields. The JSON is the whole object in a
fixed structure, so `pod["status"]["phase"]` always means the same thing.
Parsing the table would have broken on me sooner or later.

## How this tool models learning

The design comes down to four ideas I kept coming back to: you learn by
doing, feedback works best when it's immediate and specific, practice should
go where you're weakest, and progress should be measured, not guessed.

### Practice

Every task is real work on a real cluster. No multiple choice, no fake
terminal: you type the same `kubectl` commands you'd type at an internship or
a job, and a task only passes if the cluster actually ends up in the right
state. Having to come up with the command yourself (what learning research
calls retrieval practice) sticks much better than reading the answer or
picking it out of a list.

Each task resets the cluster to its own starting point first, so you can do
tasks in any order and redo them without leftovers from last time.

### Immediate feedback

`check` answers in about a second, and the answer is specific. The goal was
for every message to point at the gap between what's there and what should
be, without just handing over the command:

- **It says what's wrong:** "Pod 'web' exists but its image is 'busybox',
  expected 'nginx'."
- **It shows what's actually there:** "Pod 'web' has no 'tier' label. Its
  labels are: Tier=front, run=web." That's usually enough to spot the problem
  yourself (a capital T, in this case).
- **It knows "not yet" from "wrong":** if your container is still starting,
  you get `NOT YET` instead of `FAIL`, so you don't go "fixing" something
  that was already right. It isn't counted against you either. That one came
  from a bug I hit while rehearsing my demo: checking a couple of seconds too
  early was costing me points.
- **It knows your mistakes from broken infrastructure:** if kubectl can't
  reach the cluster, that's an ERROR, not a FAIL.
- **It notices partial progress:** "Deployment 'shop' is still on
  nginx:1.25. Now update it to nginx:1.27."

Hints are there if you need them, but you have to ask, and asking is recorded.

### Adaptive repetition

`start` doesn't go through the tasks in order. It draws one at random,
weighted toward the concepts you're weakest in:

```
weight = 0.1 + 0.9 × (1 − mastery)
```

A concept you've never tried, or scored 0% on, gets weight 1.0. At 70% it's
0.37, and once you've mastered it, 0.1. So weak concepts come up most of the
time, while mastered ones still come back for review now and then, about ten
times less often. It also never gives you the task you just did, because
practice sticks better with a gap in between. `start` tells you why it picked
a task and what chance it had, because I wanted the picking to be
transparent, not a black box.

The idea is borrowed from spaced repetition (think flashcard apps): spend
your practice time where it helps most, and keep reviewing what you already
know so it doesn't fade. Mixing concepts at random ("interleaving") also
makes you figure out which tool a problem needs, and that's most of the
battle on a real cluster.

It also adjusts itself. Practicing a weak concept raises its mastery, which
lowers its weight, which moves you on to the next weakest one.

### Measured progress

Every attempt gets saved to `data/progress.json`:

```json
{"task_id": "ns-cache", "concept": "namespaces",
 "started_at": "2026-10-05T20:41:07-04:00",
 "passed": true, "seconds": 192, "hints": 1, "failed_checks": 1}
```

Just recording pass/fail would've been pretty useless, since you can keep
trying until you pass. What matters is how you passed: on your own and
quickly, or with a hint after five wrong tries. So the report turns each
attempt into a score:

| Outcome of an attempt | Score |
|---|---|
| Not passed (yet) | 0 |
| Passed | 100 |
| ...minus, if you used the hint | −30 |
| ...minus, per failed check (at most 3) | −10 each |

A concept's mastery is the average score of its attempts:

```
  Concept      Mastery            Attempts    Avg time  Hints
  pods         [##########] 100%  1 attempt     1m 35s  0
  labels       [#######---]  70%  1 attempt     2m 20s  2
  rollouts     [####------]  40%  1 attempt    10m 10s  1
```

I'll be upfront that the 30 and 10 are judgment calls, not numbers from a
paper. They're named constants at the top of `report.py`, and the report is
recalculated from the raw history every time, so anyone can check the math
by hand or try different weights.

## What it doesn't do (yet)

A few honest limitations:

- **Your history is a plain file on your own machine.** It's a learning log,
  not a cheat-proof exam record.
- **The checks look at the end result, not how you got there.** They can't
  tell a command you worked out from one you copied off Stack Overflow.
- **Time is wall-clock time** from `start` to the passing check, so a coffee
  break counts.
- **Every attempt counts equally toward mastery,** so early struggles still
  drag a concept down after you've gotten better at it.
- **Task picking ignores difficulty,** so a total beginner might get a
  difficulty-3 task first.

If I keep working on this, here's what I'd tackle next:

1. **Real spaced repetition.** Schedule reviews by how long it's been (a day,
   then three, then a week), and weight recent attempts more, so mastery
   reflects where you are now and fades if you stop practicing.
2. **Task variations and better hints.** Randomize names, images and replica
   counts so a repeat tests the skill, not your memory of last time's answer.
   Hints would come in levels (a nudge, then the command's shape, then the
   full command), each costing a different amount.
3. **Better evidence.** Learning curves per concept over time, a record of
   which commands you actually ran, and a history file that's harder to
   tamper with.
