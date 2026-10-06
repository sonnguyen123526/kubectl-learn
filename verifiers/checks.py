"""One check_* function per task.

Each check looks at the cluster and returns (passed, message). When the
check fails, the message says what is wrong, so the learner knows what to
fix. If the work looks right but Kubernetes is still acting on it, the
check raises NotYet instead. learn.py finds these functions by name, using
each task file's "verifier" field.

Everything is checked in the default namespace unless a task says otherwise.
"""

import kube


class NotYet(Exception):
    """The work looks right, but Kubernetes hasn't finished acting on it.

    For example, a container that's still starting, or a rollout in
    progress. learn.py reports this as NOT YET and doesn't count it as a
    failed check: checking a few seconds early isn't a mistake.
    """


# --- Helpers ----------------------------------------------------------------
# Helper names start with _ so they can't be mistaken for verifiers:
# learn.py only runs functions whose names start with check_.

def _get(resource, name, namespace="default"):
    """Return the object as a dict, or None if it doesn't exist.

    Any other kubectl error (e.g. the cluster is down) is raised instead,
    because that isn't the learner's mistake and shouldn't count as a FAIL.
    """
    try:
        return kube.get_json(resource, name, namespace=namespace)
    except kube.KubectlError as err:
        if "NotFound" in err.stderr:
            return None
        raise


def _short_image(image):
    """Drop Docker Hub's default prefix: 'docker.io/library/nginx:1.27' -> 'nginx:1.27'."""
    for prefix in ("docker.io/library/", "library/"):
        if image.startswith(prefix):
            return image[len(prefix):]
    return image


def _image_repo(image):
    """Drop the tag or digest: 'nginx:1.27' -> 'nginx', 'nginx@sha256:...' -> 'nginx'."""
    image = _short_image(image).split("@")[0]
    # Only a ":" after the last "/" starts a tag. In "localhost:5000/nginx"
    # the ":" belongs to the registry address.
    if ":" in image.rsplit("/", 1)[-1]:
        image = image.rsplit(":", 1)[0]
    return image


def _images(pod_spec):
    """Return the images of every container in a pod spec, shortened."""
    return [_short_image(container["image"]) for container in pod_spec["containers"]]


def _quoted(items):
    """['a', 'b'] -> "'a', 'b'"."""
    return ", ".join(repr(item) for item in items)


def _replicas(count):
    """1 -> '1 replica', 3 -> '3 replicas'."""
    return f"{count} replica" if count == 1 else f"{count} replicas"


def _why_not_ready(pod):
    """Return why the pod isn't Ready, or None if it is.

    Raises NotYet if the pod is only still starting.
    """
    name = pod["metadata"]["name"]
    status = pod.get("status", {})
    for condition in status.get("conditions", []):
        if condition["type"] == "Ready" and condition["status"] == "True":
            return None

    # A container that isn't running has a "waiting" state whose reason
    # says why, e.g. ContainerCreating, ErrImagePull, CrashLoopBackOff.
    for container in status.get("containerStatuses", []):
        waiting = container.get("state", {}).get("waiting")
        if not waiting:
            continue
        reason = waiting.get("reason", "Waiting")
        if reason in ("ContainerCreating", "PodInitializing"):
            raise NotYet(f"Pod '{name}' is still starting ({reason}).")
        detail = waiting.get("message")
        return f"its container is stuck in {reason}" + (f": {detail}" if detail else "")

    # No container is stuck, so it's on its way, e.g. just scheduled.
    raise NotYet(f"Pod '{name}' is {status.get('phase', 'Pending')} but not Ready yet.")


def _rollout_problem(deploy, unavailable_advice=None):
    """Return why a deployment isn't fully rolled out and available, or None.

    Uses the same test as `kubectl rollout status`. Kubernetes leaves out
    status fields that are 0, hence .get(..., 0).

    A rollout in progress raises NotYet. So do pods that exist but aren't
    available yet, unless unavailable_advice is given: then that's a real
    problem (e.g. the debugging task's crashing pods), returned with the
    advice appended.
    """
    name = deploy["metadata"]["name"]
    replicas = deploy["spec"].get("replicas", 1)
    status = deploy.get("status", {})
    updated = status.get("updatedReplicas", 0)
    available = status.get("availableReplicas", 0)
    old = status.get("replicas", 0) - updated

    if (
        status.get("observedGeneration", 0) < deploy["metadata"]["generation"]
        or updated < replicas
        or old > 0
    ):
        raise NotYet(
            f"Deployment '{name}' is still rolling out: {updated} of {replicas} pods are on "
            f"the new version and {old} old pods haven't been replaced yet."
        )
    if available < replicas:
        if unavailable_advice is None:
            raise NotYet(f"Deployment '{name}' has {available} of {replicas} pods available.")
        return f"Deployment '{name}' has {available} of {replicas} pods available. {unavailable_advice}"
    return None


# --- Verifiers --------------------------------------------------------------
# Checks run in the order a learner would make progress, so the first
# failure is the next thing to fix.

def check_pod_web():
    pod = _get("pod", "web")
    if pod is None:
        return False, "There's no pod named 'web' in the default namespace."

    images = _images(pod["spec"])
    if "nginx" not in [_image_repo(image) for image in images]:
        return False, f"Pod 'web' exists but its image is {_quoted(images)}, expected 'nginx'."

    problem = _why_not_ready(pod)
    if problem:
        return False, f"Pod 'web' runs nginx, but {problem}."

    return True, "Pod 'web' is running nginx."


def check_deploy_api():
    deploy = _get("deployment", "api")
    if deploy is None:
        return False, "There's no deployment named 'api' in the default namespace."

    pod_spec = deploy["spec"]["template"]["spec"]
    images = _images(pod_spec)
    if "nginx:1.27" not in images:
        return False, f"Deployment 'api' uses {_quoted(images)}, expected 'nginx:1.27'."

    ports = [port["containerPort"] for c in pod_spec["containers"] for port in c.get("ports", [])]
    if 80 not in ports:
        declared = f"It declares {ports}." if ports else "It declares no ports."
        return False, f"Deployment 'api' doesn't declare container port 80. {declared}"

    replicas = deploy["spec"].get("replicas", 1)
    if replicas != 3:
        return False, f"Deployment 'api' is set to {_replicas(replicas)}, expected 3."

    problem = _rollout_problem(deploy)
    if problem:
        return False, problem

    return True, "Deployment 'api' has 3 ready nginx:1.27 pods with port 80."


def check_scale_cart():
    deploy = _get("deployment", "cart")
    if deploy is None:
        return False, "There's no deployment named 'cart'. Run `kubectl-learn reset` to recreate it."

    replicas = deploy["spec"].get("replicas", 1)
    if replicas != 4:
        return False, f"Deployment 'cart' is set to {_replicas(replicas)}, expected 4."

    problem = _rollout_problem(deploy)
    if problem:
        return False, problem

    return True, "Deployment 'cart' is scaled to 4 ready pods."


# The env label each pod gets from setup. Only the env=dev ones should
# end up with tier=test.
APP_PODS = {"app-1": "prod", "app-2": "dev", "app-3": "prod", "app-4": "dev"}


def check_label_select():
    # One `kubectl get pods` for all four, instead of four separate calls.
    pods = {pod["metadata"]["name"]: pod for pod in kube.get_json("pods")["items"]}

    for name, env in APP_PODS.items():
        if name not in pods:
            return False, f"Pod '{name}' is gone. Run `kubectl-learn reset` to recreate the pods."

        labels = pods[name]["metadata"].get("labels", {})
        if labels.get("env") != env:
            return False, (
                f"Pod '{name}' should still have env={env}, but it has env={labels.get('env')}. "
                "Only add labels; leave env as it was."
            )

        tier = labels.get("tier")
        if env == "dev" and tier is None:
            return False, f"Pod '{name}' has env=dev but no tier label."
        if env == "dev" and tier != "test":
            return False, f"Pod '{name}' has tier={tier}, expected tier=test."
        if env != "dev" and tier is not None:
            return False, f"Pod '{name}' has tier={tier}, but it's env={env}. Only env=dev pods should get it."

    return True, "Exactly the env=dev pods (app-2 and app-4) have tier=test."


def check_ns_cache():
    namespace = _get("namespace", "team-a")
    if namespace is None:
        # The most common mistake: forgetting -n, so the pod lands in default.
        if _get("pod", "cache") is not None:
            return False, (
                "Pod 'cache' is in the default namespace, and there's no namespace "
                "'team-a' yet. Create the namespace, then run the pod inside it."
            )
        return False, "There's no namespace named 'team-a'."
    phase = namespace.get("status", {}).get("phase")
    if phase != "Active":
        return False, f"Namespace 'team-a' is {phase}. Wait until it's gone, then create it again."

    pod = _get("pod", "cache", namespace="team-a")
    if pod is None:
        if _get("pod", "cache") is not None:
            return False, "Pod 'cache' is in the default namespace, but it should be in team-a."
        return False, "There's no pod named 'cache' in the team-a namespace."

    images = _images(pod["spec"])
    if "redis" not in [_image_repo(image) for image in images]:
        return False, f"Pod 'cache' uses {_quoted(images)}, expected 'redis'."

    problem = _why_not_ready(pod)
    if problem:
        return False, f"Pod 'cache' runs redis, but {problem}."

    return True, "Pod 'cache' is running redis in namespace team-a."


def check_shop_rollout():
    deploy = _get("deployment", "shop")
    if deploy is None:
        return False, "There's no deployment named 'shop' in the default namespace."

    replicas = deploy["spec"].get("replicas", 1)
    if replicas != 2:
        return False, f"Deployment 'shop' has {_replicas(replicas)}, expected 2."

    images = _images(deploy["spec"]["template"]["spec"])
    if "nginx:1.27" not in images:
        if "nginx:1.25" in images:
            return False, "Deployment 'shop' is still on nginx:1.25. Now update it to nginx:1.27."
        return False, f"Deployment 'shop' uses {_quoted(images)}, expected 'nginx:1.27'."

    # Kubernetes adds 1 to this annotation every time the pod template
    # changes, i.e. on every rollout. A deployment created on nginx:1.25
    # and then updated once is at revision 2.
    annotations = deploy["metadata"].get("annotations", {})
    revision = int(annotations.get("deployment.kubernetes.io/revision", "0"))
    if revision < 2:
        return False, (
            "Deployment 'shop' was created with nginx:1.27, so no rollout happened. "
            "Delete it, create it on nginx:1.25, then update it to nginx:1.27."
        )

    problem = _rollout_problem(deploy)
    if problem:
        return False, problem

    return True, "Deployment 'shop' has rolled out nginx:1.27 to 2 replicas."


# What the configmap should contain, and so what the pod's environment
# should contain.
APP_CONFIG = {"MODE": "debug", "LOG_LEVEL": "info"}


def check_configmap_env():
    configmap = _get("configmap", "app-config")
    if configmap is None:
        return False, "There's no configmap named 'app-config' in the default namespace."

    data = configmap.get("data", {})
    for key, value in APP_CONFIG.items():
        if key not in data:
            shown = ", ".join(f"{k}={v}" for k, v in data.items()) or "none"
            return False, f"Configmap 'app-config' has no {key} entry. Its entries are: {shown}."
        if data[key] != value:
            return False, f"Configmap 'app-config' has {key}={data[key]}, expected {key}={value}."

    pod = _get("pod", "configured")
    if pod is None:
        return False, "There's no pod named 'configured' in the default namespace."

    images = _images(pod["spec"])
    if "nginx" not in [_image_repo(image) for image in images]:
        return False, f"Pod 'configured' uses {_quoted(images)}, expected 'nginx'."

    # The pod must read the values from app-config, not have them typed in.
    # Either envFrom (every entry) or env with configMapKeyRef (one by one).
    container = pod["spec"]["containers"][0]
    reads_all = any(
        source.get("configMapRef", {}).get("name") == "app-config"
        for source in container.get("envFrom", [])
    )
    keys_read = {
        var["name"] for var in container.get("env", [])
        if var.get("valueFrom", {}).get("configMapKeyRef", {}).get("name") == "app-config"
    }
    if not reads_all and not set(APP_CONFIG) <= keys_read:
        return False, (
            "Pod 'configured' doesn't load its environment from app-config. "
            "Its container needs an envFrom entry with a configMapRef to app-config."
        )

    problem = _why_not_ready(pod)
    if problem:
        return False, f"Pod 'configured' exists, but {problem}."

    # Finally, look inside the running container. Environment variables are
    # read once, when the container starts, so a configmap edited after
    # that isn't reflected here.
    env = dict(
        line.split("=", 1)
        for line in kube.run(["exec", "configured", "--", "env"]).splitlines()
        if "=" in line
    )
    for key, value in APP_CONFIG.items():
        if env.get(key) != value:
            actual = "isn't set" if key not in env else f"is {env[key]!r}"
            return False, (
                f"Inside pod 'configured', {key} {actual}, but app-config says {value!r}. "
                "A container reads its environment only when it starts, so recreate the pod."
            )

    return True, "Pod 'configured' gets MODE=debug and LOG_LEVEL=info from app-config."


def check_debug_frontend():
    deploy = _get("deployment", "frontend")
    if deploy is None:
        return False, "There's no deployment named 'frontend'. Run `kubectl-learn reset` to recreate it."

    replicas = deploy["spec"].get("replicas", 1)
    if replicas != 2:
        return False, f"Deployment 'frontend' is set to {_replicas(replicas)}; it should run 2."

    images = _images(deploy["spec"]["template"]["spec"])
    if "nginx" not in [_image_repo(image) for image in images]:
        return False, f"Deployment 'frontend' uses {_quoted(images)}; it should keep using nginx."

    # Deliberately vague: finding the cause is the task.
    problem = _rollout_problem(deploy, unavailable_advice="Find out what its pods are doing.")
    if problem:
        return False, problem

    return True, "Deployment 'frontend' has 2 nginx pods running and ready."
