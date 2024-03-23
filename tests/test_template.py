"""Static checks on the SAM template. It is never deployed by the tests."""

import importlib
import inspect
from pathlib import Path

import yaml

from url_shortener import store

ROOT = Path(__file__).parent.parent


class _Loader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {tag_suffix: value}


_Loader.add_multi_constructor("!", _intrinsic)

TEMPLATE = yaml.load((ROOT / "template.yaml").read_text(), Loader=_Loader)
FUNCTION = TEMPLATE["Resources"]["ShortenerFunction"]["Properties"]


def test_handler_path_points_at_real_code():
    module_name, function_name = FUNCTION["Handler"].rsplit(".", 1)
    assert (ROOT / FUNCTION["CodeUri"] / module_name.replace(".", "/")).with_suffix(".py").exists()
    module = importlib.import_module(module_name)
    assert list(inspect.signature(getattr(module, function_name)).parameters) == ["event", "context"]


def test_iam_policy_is_exactly_what_the_store_calls():
    (policy,) = FUNCTION["Policies"]
    (statement,) = policy["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Resource"] == {"GetAtt": "LinksTable.Arn"}
    assert sorted(statement["Action"]) == ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    source = inspect.getsource(store)
    for used in ("get_item(", "put_item(", "update_item("):
        assert used in source
    for unused in ("scan(", "query(", "delete_item(", "batch_"):
        assert unused not in source


def test_table_matches_the_code():
    table = TEMPLATE["Resources"]["LinksTable"]["Properties"]
    assert table["KeySchema"] == [{"AttributeName": "slug", "KeyType": "HASH"}]
    assert table["TimeToLiveSpecification"] == {"AttributeName": "expires_at", "Enabled": True}
    assert '"expires_at"' in inspect.getsource(store)


def test_routes_and_environment():
    routes = {(e["Properties"]["Method"], e["Properties"]["Path"]) for e in FUNCTION["Events"].values()}
    assert routes == {("POST", "/links"), ("GET", "/links/{slug}"), ("GET", "/{slug}")}
    assert all(e["Type"] == "HttpApi" for e in FUNCTION["Events"].values())
    env = FUNCTION["Environment"]["Variables"]
    assert env == {
        "TABLE_NAME": {"Ref": "LinksTable"},
        "CREATE_TOKEN": {"Ref": "CreateToken"},
        "DEFAULT_TTL_SECONDS": {"Ref": "DefaultTtlSeconds"},
    }
    assert TEMPLATE["Parameters"]["CreateToken"]["NoEcho"] is True
