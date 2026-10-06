# kubectl-learn: 5-minute demo

The demo follows one task from start to finish: start it, make a realistic
mistake, get feedback, fix it, pass, and then show the report of your real
practice history.

The task is `ns-cache` (create a namespace and run a redis pod in it). It's
quick, and the most common mistake with it, forgetting `-n`, shows off the
feedback well.

## Before you present (not timed)

1. **Practice for real in the days before.** The report at the end should
   show genuine history, so do several real `start`/`check` sessions
   beforehand. Don't edit `data/progress.json`. Its value as evidence is that
   it's what really happened.
2. **Check that the cluster is up:**
   ```bash
   kubectl config current-context   # kind-learn
   kubectl get nodes                # STATUS Ready
   ```
3. **Pull the redis image ahead of time,** so the pod starts in seconds:
   ```bash
   kubectl run warmup --image=redis && kubectl wait --for=condition=Ready pod/warmup --timeout=120s && kubectl delete pod warmup --now
   ```
4. **Back up your history.** The mistake in the demo is staged, so you'll
   probably want to remove it afterwards:
   ```bash
   cp -R data data.before-demo
   ```
5. **Start from a clean cluster,** set a large terminal font, and clear the screen:
   ```bash
   kubectl-learn reset
   clear
   ```

## The script

### 0:00–0:40 · The idea (talk only)

> "Reading kubectl docs doesn't make you good at kubectl. Typing commands
> against a real cluster does. kubectl-learn is a tutor that gives me real
> tasks on a local kind cluster, checks my work by inspecting the cluster,
> tells me exactly what's wrong, records every attempt, and picks my next
> task based on what I'm weakest at. Let me show you one round."

### 0:40–1:20 · Start a task

```bash
kubectl-learn start ns-cache
```

```
Clearing out anything left from earlier attempts:
  $ kubectl delete namespace team-a --ignore-not-found
  $ kubectl delete pod cache --ignore-not-found --now

Task: Work in a namespace  (concept: namespaces, difficulty: 2/3)
You chose this task.

Create a namespace named team-a. Then, inside team-a, run a pod named cache that uses the redis image.

Stuck? Run: kubectl-learn hint
Done?  Run: kubectl-learn check
```

Point out:
- **The cleanup lines.** Each task resets the cluster to its starting point
  first, so tasks can be repeated and done in any order.
- **"You chose this task."** I named the task for the demo. Normally `start`
  picks one for me, and I'll show that at the end.

### 1:20–2:10 · Make the most common mistake

```bash
kubectl run cache --image=redis
kubectl-learn check
```

```
FAIL: Pod 'cache' is in the default namespace, and there's no namespace 'team-a' yet. Create the namespace, then run the pod inside it.
Stuck? Run: kubectl-learn hint
```

> "I forgot `-n`, which is the classic namespace mistake. The check doesn't
> just say FAIL. It found my pod, told me where it ended up and what's
> missing, without giving me the command. Each task has a verifier function
> that reads the cluster's state as JSON through kubectl."

### 2:10–3:00 · Fix it and pass

```bash
kubectl create namespace team-a
kubectl run cache --image=redis -n team-a
kubectl-learn check
```

If you check within a second or two, you'll see:

```
NOT YET: Pod 'cache' is still starting (ContainerCreating). Check again in a few seconds.
```

> "NOT YET isn't FAIL. My work is right; Kubernetes is still starting the
> container. Checking early isn't a mistake, so it isn't counted against me."

```bash
kubectl-learn check
```

```
PASS: Pod 'cache' is running redis in namespace team-a.
Time: 7s  Hints: 0  Failed checks: 1
Next task: kubectl-learn start
```

> "It recorded this attempt: how long it took, whether I needed a hint, and
> how many checks failed first. Pass or fail alone wouldn't separate solving
> it on my own from getting there after five wrong tries."

### 3:00–4:15 · The report

```bash
kubectl-learn report
```

Walk through it from top to bottom. Your numbers will be your own; this is
what each part shows:

| Line | What to say |
|---|---|
| `Practice: <first day> to <last day>` | "This is my real practice history, over these dates." |
| `Attempts` / `Pass rate` | "Pass rate ends up near 100%, because the tool keeps me on a task until I pass, so on its own it proves little." |
| `First try` | "This is more telling: how many passes needed no failed checks." |
| The mastery bars | "Mastery per concept. A pass scores 100, minus 30 if I used the hint and 10 per failed check. The formula is printed at the bottom, so anyone can check it." |
| `Avg time` / `Hints` | "How fluent I am, and how much help I needed." |
| `Weakest concepts` | "Where I should practice next, and why each one scores low." |

> "Every number comes from `data/progress.json`, one timestamped record per
> attempt, recalculated each time I run the report."

### 4:15–4:40 · The adaptive pick

```bash
kubectl-learn start
```

```
Task: ...
Picked because your <concept> mastery is <N>% (<M>% chance this time).
```

> "Without a task name, `start` draws at random, weighted toward my weak
> concepts. A concept I haven't learned is about ten times more likely than
> one I've mastered, but mastered ones still come back for review. It's the
> idea behind spaced repetition: practice where it does the most good, and
> keep reviewing so I don't forget."

### 4:40–5:00 · Wrap-up

> "So the tool models learning in four ways: **practice** on a real cluster,
> **immediate, specific feedback**, **adaptive repetition** of weak areas,
> and **measured progress** you can check. Next, I'd like to add
> time-based spaced repetition, randomized task variations, and learning
> curves over time."

## After the demo

```bash
kubectl-learn reset                              # clean the cluster
rm -rf data && mv data.before-demo data          # drop the staged demo attempt from your history
```

Restoring the backup keeps your history to genuine practice. The demo
attempt included a deliberate mistake, and the adaptive `start` left an
attempt open.

## If something goes wrong

| What you see | What to do |
|---|---|
| `ERROR: couldn't check the cluster` | The cluster isn't running. `docker start learn-control-plane`, wait a few seconds, then check again. |
| `NOT YET` keeps repeating | The image is still downloading. `kubectl get pods -n team-a` shows the status; wait, or explain while it finishes. |
| You made an unplanned mistake | Use it! Run `check` and talk about the message. `kubectl-learn reset` restores the task's starting point. |
| Running short on time | Skip the adaptive pick (4:15) and go straight to the wrap-up. |

## Questions you might get

- **"Can't you just edit the progress file?"** Yes. It's a learning log,
  not an exam system. Tamper-evident logging would be future work.
- **"Why 30 points for a hint and 10 for a failed check?"** They're
  judgment calls, kept as named constants in `report.py`. The report is
  recalculated from the raw history, so other weights can be tried instantly.
- **"How does `check` know which function to run?"** The task file names its
  verifier, and `getattr(checks, name)` looks the function up at runtime.
- **"Couldn't you copy commands from the internet?"** Yes. Verifiers check
  the end result, not how you got there. Hints you ask for are recorded,
  though.
