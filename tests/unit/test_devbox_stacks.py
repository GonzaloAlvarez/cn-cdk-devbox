import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from devbox.base_stack import DevboxBaseStack
from devbox.box_stack import DevboxBoxStack, instance_arch

ENV = cdk.Environment(account="111111111111", region="us-east-2")


def synth():
    app = cdk.App()
    base = DevboxBaseStack(app, "DevboxBase", env=ENV)
    box = DevboxBoxStack(app, "Devbox-tst1", base=base, box_name="tst1",
                         instance_type_str="m7g.large", disk_gib=50,
                         plugins="kauket", autostop="6h", env=ENV)
    return Template.from_stack(base), Template.from_stack(box)


@pytest.fixture(scope="module")
def templates():
    return synth()


def test_arch_helper():
    assert instance_arch("m7g.large") == "arm64"
    assert instance_arch("t4g.small") == "arm64"
    assert instance_arch("c6gn.xlarge") == "arm64"
    assert instance_arch("g5g.xlarge") == "arm64"
    assert instance_arch("m7i.xlarge") == "amd64"
    assert instance_arch("c5.large") == "amd64"
    assert instance_arch("g4dn.xlarge") == "amd64"


def test_sg_has_no_external_ingress(templates):
    base, _ = templates
    # The SG resource itself carries no inline ingress rules
    for sg in base.find_resources("AWS::EC2::SecurityGroup").values():
        assert "SecurityGroupIngress" not in sg["Properties"]
    # Exactly one standalone ingress rule: the self-reference, no CIDR source
    base.resource_count_is("AWS::EC2::SecurityGroupIngress", 1)
    base.has_resource_properties("AWS::EC2::SecurityGroupIngress", {
        "SourceSecurityGroupId": Match.any_value(),
        "IpProtocol": "-1",
        "CidrIp": Match.absent(),
        "CidrIpv6": Match.absent(),
    })


def test_base_has_no_nat_and_public_subnets_only(templates):
    base, _ = templates
    base.resource_count_is("AWS::EC2::NatGateway", 0)


def test_role_policies(templates):
    base, _ = templates
    base.has_resource_properties("AWS::IAM::Role", {
        "ManagedPolicyArns": Match.array_with([
            Match.object_like({"Fn::Join": Match.array_with([
                Match.array_with([Match.string_like_regexp(".*AmazonSSMManagedInstanceCore")])
            ])})
        ]),
    })
    base.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": Match.object_like({
            "Statement": Match.array_with([
                Match.object_like({
                    "Action": "ssm:GetParameter",
                    "Resource": Match.object_like({"Fn::Join": Match.array_with([
                        Match.array_with([Match.string_like_regexp(":parameter/devbox/\\*")])
                    ])}),
                })
            ]),
        }),
    })


def test_instance_imdsv2_required(templates):
    _, box = templates
    box.has_resource_properties("AWS::EC2::LaunchTemplate", {
        "LaunchTemplateData": Match.object_like({
            "MetadataOptions": {"HttpTokens": "required"},
        }),
    })


def test_instance_shape(templates):
    _, box = templates
    box.has_resource_properties("AWS::EC2::Instance", {
        "InstanceType": "m7g.large",
        "InstanceInitiatedShutdownBehavior": "stop",
        "PropagateTagsToVolumeOnCreation": True,
        "KeyName": Match.absent(),
        "BlockDeviceMappings": [Match.object_like({
            "DeviceName": "/dev/xvda",
            "Ebs": Match.object_like({
                "VolumeType": "gp3",
                "Encrypted": True,
                "VolumeSize": 50,
                "DeleteOnTermination": True,
            }),
        })],
        "Tags": Match.array_with([
            {"Key": "devbox:managed-by", "Value": "clouddevbox"},
            {"Key": "devbox:name", "Value": "tst1"},
        ]),
    })


def test_user_data_rendering(templates):
    _, box = templates
    blob = json.dumps(box.to_json())
    assert "devbox-autostop.timer" in blob
    assert "devbox-tst1" in blob
    assert "/devbox/tst1/ts-authkey" in blob
    assert "go.gn.al/amun" in blob
    assert "--login-server=https://hs.gn.al" in blob
    assert "/etc/clouddevbox/plugins" in blob
    assert "/var/lib/clouddevbox/provisioned" in blob


def test_no_lambda_assets(templates):
    # Both stacks must stay asset-free so `cdk deploy` works without
    # `cdk bootstrap` (guards @aws-cdk/aws-ec2:restrictDefaultSecurityGroup=false)
    base, box = templates
    base.resource_count_is("AWS::Lambda::Function", 0)
    box.resource_count_is("AWS::Lambda::Function", 0)
