"""The least-privilege proof itself must be strict: only AccessDenied counts as denied."""
import importlib.util
from pathlib import Path

from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location(
    "prove", Path(__file__).resolve().parent.parent / "security" / "prove_least_privilege.py")
prove = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prove)


class FakeBedrock:
    def __init__(self, outcomes):
        self.outcomes = outcomes            # model id -> error code, or None for allowed

    def _maybe_fail(self, model_id):
        code = self.outcomes.get(model_id)
        if code:
            raise ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")

    def converse(self, modelId, **kwargs):
        self._maybe_fail(modelId)

    def invoke_model(self, modelId, **kwargs):
        self._maybe_fail(modelId)


DENIED = {m: "AccessDeniedException" for _, _, m in prove.MUST_DENY}


def test_correct_policy_passes():
    assert all(ok for *_, ok in prove.check(FakeBedrock(DENIED)))


def test_throttling_is_not_a_denial():
    outcomes = dict(DENIED, **{"us.amazon.nova-pro-v1:0": "ThrottlingException"})
    rows = prove.check(FakeBedrock(outcomes))
    assert not rows[0][3]                   # IAM let it through; only the quota stopped it


def test_an_allowed_unapproved_model_fails():
    outcomes = dict(DENIED)
    outcomes.pop("us.amazon.nova-pro-v1:0")  # Nova Pro succeeds
    assert not all(ok for *_, ok in prove.check(FakeBedrock(outcomes)))


def test_broken_credentials_fail_the_positive_control():
    outcomes = dict(DENIED, **{"us.amazon.nova-lite-v1:0": "AccessDeniedException"})
    assert not prove.check(FakeBedrock(outcomes))[-1][3]
