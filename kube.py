"""kube: run kubectl from Python and get its output back."""

import json
import shlex
import subprocess


class KubectlError(Exception):
    """kubectl couldn't be started, timed out, or exited with an error.

    The attributes let callers look at what went wrong. For example, a
    verifier can check for "NotFound" in `err.stderr` to tell "the pod
    doesn't exist" apart from "the cluster is down".
    """

    def __init__(self, message, cmd, returncode=None, stderr=""):
        super().__init__(message)
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr


def run(args, timeout=30):
    """Run `kubectl <args>` and return what it printed to stdout.

    args is a list, one item per word: ["get", "pods"], not "get pods".
    Raises KubectlError if kubectl is missing, takes longer than `timeout`
    seconds, or exits with a nonzero code.
    """
    # A string would be unpacked one character at a time below
    # ("k", "u", "b", ...), so catch that mistake with a clear message.
    if isinstance(args, str):
        raise TypeError(f"args must be a list, e.g. {args.split()!r}")

    cmd = ["kubectl", *args]
    # shlex.join quotes the words the way a shell would, so error messages
    # show a command you can copy and paste into your terminal.
    shown = shlex.join(cmd)

    try:
        # capture_output=True: collect stdout/stderr instead of printing them.
        # text=True: decode the bytes to str.
        # No check=True: we look at returncode ourselves to build our error.
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        # The OS couldn't find a "kubectl" program on your PATH.
        raise KubectlError("kubectl not found. Is it installed and on your PATH?", cmd) from None
    except subprocess.TimeoutExpired:
        # Usually means the cluster isn't reachable (e.g. kind isn't running).
        raise KubectlError(f"`{shown}` took longer than {timeout}s. Is the cluster running?", cmd) from None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise KubectlError(
            f"`{shown}` failed (exit code {result.returncode}):\n{stderr}",
            cmd,
            returncode=result.returncode,
            stderr=stderr,
        )
    return result.stdout


def get_json(resource, name=None, namespace="default"):
    """Run `kubectl get <resource> [name] -o json` and return the parsed JSON.

    With a name you get that one object as a dict. Without one you get a
    dict with kind "List" whose "items" holds every match. namespace is
    ignored for cluster-wide resources like nodes.
    """
    args = ["get", resource]
    if name is not None:
        args.append(name)
    args += ["--namespace", namespace, "--output", "json"]
    return json.loads(run(args))
