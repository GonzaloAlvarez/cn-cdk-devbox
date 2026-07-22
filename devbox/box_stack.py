import re
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Stack,
    Tags,
    aws_ec2 as ec2,
)
from constructs import Construct

# Debian publishes per-region AMI ids as public SSM parameters.
DEBIAN_SSM_PARAM = "/aws/service/debian/release/13/latest/{arch}"

FAMILY_RE = re.compile(r"^([a-z]+)([0-9]+)([a-z-]*)$")


def instance_arch(instance_type: str) -> str:
    """arm64 vs amd64 from the instance family: a 'g' in the letters after
    the generation digit means Graviton (m7g, t4g, c6gn, g5g); everything
    else is x86 (m7i, c5, g4dn)."""
    family = instance_type.split(".")[0]
    m = FAMILY_RE.match(family)
    if not m:
        raise ValueError(f"unrecognized instance family '{family}'")
    return "arm64" if "g" in m.group(3) else "amd64"


class DevboxBoxStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, *,
                 base, box_name: str, instance_type_str: str,
                 disk_gib: int, plugins: str, autostop: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # cached_in_context pins the AMI in cdk.context.json: without it the
        # parameter re-resolves on every deploy, and a newer Debian AMI would
        # REPLACE the instance (and its root volume) on an innocent update.
        machine_image = ec2.MachineImage.from_ssm_parameter(
                DEBIAN_SSM_PARAM.format(arch=instance_arch(instance_type_str)),
                os=ec2.OperatingSystemType.LINUX,
                cached_in_context=True,
                )

        plugin_list = " ".join(p for p in plugins.split(",") if p)
        template = (Path(__file__).resolve().parent.parent / "user-data.sh.tmpl").read_text()
        rendered = (template
                    .replace("__BOX_NAME__", box_name)
                    .replace("__PLUGINS__", plugin_list)
                    .replace("__AUTOSTOP__", autostop))
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(rendered)

        instance = ec2.Instance(self, "Instance",
                vpc=base.vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                security_group=base.sg,
                role=base.role,
                instance_type=ec2.InstanceType(instance_type_str),
                machine_image=machine_image,
                user_data=user_data,
                require_imdsv2=True,
                propagate_tags_to_volume_on_creation=True,
                instance_name=f"devbox-{box_name}",
                block_devices=[ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        disk_gib,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=True,
                    ),
                )],
                )

        # On-box `systemctl poweroff` (the autostop timer) must STOP the
        # instance, never terminate it.
        instance.instance.instance_initiated_shutdown_behavior = "stop"

        Tags.of(self).add("devbox:name", box_name)
        Tags.of(self).add("devbox:managed-by", "clouddevbox")

        CfnOutput(self, 'instanceid', value=instance.instance_id)
        CfnOutput(self, 'privateip', value=instance.instance_private_ip)
