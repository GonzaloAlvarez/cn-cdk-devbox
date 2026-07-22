from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
)
from constructs import Construct


class DevboxBaseStack(Stack):
    """Shared infrastructure for every devbox: one VPC, one SG, one role.

    Construct IDs in this stack are FROZEN once any Devbox-* stack exists:
    box stacks consume vpc/sg/role through automatic cross-stack exports,
    and renaming a construct here (or changing what box stacks import)
    makes CloudFormation try to remove an export a live box still uses.
    """

    VPC_CIDR = "10.81.0.0/16"

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Public subnets only, no NAT: instances get a public IP for
        # outbound; the SG below makes them unreachable from outside.
        self.vpc = ec2.Vpc(self, "DevboxVPC",
                ip_addresses=ec2.IpAddresses.cidr(self.VPC_CIDR),
                max_azs=2,
                nat_gateways=0,
                enable_dns_support=True,
                subnet_configuration=[
                    ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ]
                )

        # The only ingress rule is the self-reference: devboxes reach each
        # other on any port over their 10.81.x.y private IPs, while no
        # external source (no CIDR rule at all) can connect in.
        self.sg = ec2.SecurityGroup(self, "DevboxSG",
                vpc=self.vpc,
                description="Devbox shared SG - no external ingress",
                security_group_name="DevboxSG",
                allow_all_outbound=True,
                )
        self.sg.add_ingress_rule(
                peer=self.sg,
                connection=ec2.Port.all_traffic(),
                description="devbox to devbox",
                )

        # SSM Session Manager (break-glass access) + read of the one-shot
        # tailscale preauth key that clouddevbox stages under /devbox/<name>/.
        self.role = iam.Role(self, "DevboxRole",
                assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                ],
                )
        self.role.add_to_policy(iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[self.format_arn(service="ssm", resource="parameter", resource_name="devbox/*")],
                ))
