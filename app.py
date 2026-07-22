import os
import re

import aws_cdk as cdk

from devbox.base_stack import DevboxBaseStack
from devbox.box_stack import DevboxBoxStack

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,22}[a-z0-9]$")
AUTOSTOP_RE = re.compile(r"^([0-9]+[hm]|off)$")

account_id = os.environ.get("AWS_ACCOUNT_ID")
if not account_id:
    raise SystemExit("AWS_ACCOUNT_ID is required (clouddevbox / manage.sh derive it via STS)")

env = cdk.Environment(account=account_id, region="us-east-2")

app = cdk.App()
base = DevboxBaseStack(app, "DevboxBase", env=env)

# Which devboxes exist is CloudFormation state, not code: the app only ever
# defines the single box named via -c box=<name>. Other Devbox-* stacks in
# the account are untouched by any deploy of this app.
box = app.node.try_get_context("box")
if box:
    if not NAME_RE.match(box) or box == "base":
        raise SystemExit(
            f"invalid box name '{box}': lowercase alphanumeric + dashes, "
            f"2-24 chars, must not be 'base'"
        )
    autostop = app.node.try_get_context("autostop") or "6h"
    if not AUTOSTOP_RE.match(autostop):
        raise SystemExit(f"invalid autostop '{autostop}': use <N>h, <N>m or off")
    DevboxBoxStack(
        app,
        f"Devbox-{box}",
        base=base,
        box_name=box,
        instance_type_str=app.node.try_get_context("type") or "m7g.large",
        disk_gib=int(app.node.try_get_context("disk") or "50"),
        plugins=app.node.try_get_context("plugins") if app.node.try_get_context("plugins") is not None else "kauket",
        autostop=autostop,
        env=env,
    )

app.synth()
