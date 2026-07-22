# cn-cdk-devbox

AWS CDK (Python) app for on-demand cloud devboxes in `us-east-2`. Two stack
shapes:

- **`DevboxBase`** — deployed once per account: VPC `10.81.0.0/16` (public
  subnets, no NAT, $0 standing cost), one shared security group with **zero
  external ingress** (only a self-referencing allow-all so devboxes reach
  each other over private IPs), and the instance IAM role
  (`AmazonSSMManagedInstanceCore` + read of `/devbox/*` SSM parameters).
- **`Devbox-<name>`** — one stack per box, created only when the CDK context
  `-c box=<name>` is passed. CloudFormation is the record of which boxes
  exist; this app never enumerates them, so deploying one box never touches
  another.

Each box: Debian 13 (AMI via the public SSM parameter
`/aws/service/debian/release/13/latest/<arch>`, arch derived from the
instance type), default `m7g.large` + 50 GB gp3 (encrypted), IMDSv2
required, **no key pair, no EIP, no open ports**. Access is tailnet SSH
(headscale at `hs.gn.al`) and SSM Session Manager only.

## Normally driven by `clouddevbox`

The [cn-cli-devbox](https://github.com/GonzaloAlvarez/cn-cli-devbox) CLI
wraps this app and also handles the piece CDK can't: minting a one-shot
headscale preauth key and staging it at
`/devbox/<name>/ts-authkey` (SSM SecureString) for the instance to consume
at first boot. `./manage.sh deploy <box>` skips that handoff — the box will
come up but never join the tailnet.

## Context arguments

| Context | Default | Meaning |
|---|---|---|
| `box` | — | box name (`^[a-z][a-z0-9-]{0,22}[a-z0-9]$`) |
| `type` | `m7g.large` | EC2 instance type; arch (arm64/amd64) is derived |
| `disk` | `50` | root gp3 volume GiB |
| `plugins` | `kauket` | comma-separated `amun-<plugin>` list run after amun core |
| `autostop` | `6h` | self-stop after this uptime (`<N>h`, `<N>m`, `off`) |

## manage.sh

```sh
./manage.sh test              # pytest (synth-level assertions)
./manage.sh synth tst1        # inspect templates
./manage.sh deploy            # deploy/update DevboxBase only
./manage.sh deploy tst1       # base + Devbox-tst1 (no authkey handoff!)
./manage.sh destroy tst1      # destroy one box
./manage.sh destroy           # destroy base (fails while boxes exist)
```

Needs `AWS_PROFILE` (account ID auto-discovered via STS) and `node` on PATH.
`.venv`/`.npm` are created per run and removed on exit.

## Invariants (read before editing)

- **Never re-deploy a live box.** The AMI is pinned per-checkout in the
  gitignored `cdk.context.json` (`cached_in_context=True`); on a fresh
  checkout the parameter resolves to a *newer* Debian AMI and an innocent
  `cdk deploy Devbox-<name>` would **replace the instance and its root
  volume**. Boxes are cattle: destroy + recreate instead.
- **Construct IDs in `DevboxBaseStack` are frozen** once any box stack
  exists: box stacks import vpc/sg/role via automatic cross-stack exports,
  and renaming a construct makes CloudFormation try to remove an export a
  live box still uses (deploy fails with "Export in use").
- **Keep the stacks asset-free** (no Lambda/custom resources — guarded by a
  unit test): that is what lets `cdk deploy` run in accounts that were never
  `cdk bootstrap`-ped.
- On-box `systemctl poweroff` (the autostop timer) maps to EC2 **STOP**
  (`InstanceInitiatedShutdownBehavior: stop`) — a stopped box costs only its
  EBS volume (~$4/mo at 50 GB).

## Bootstrap sequence (user-data)

SSM agent → `gonzalo` user (NOPASSWD sudo, authorized_keys from the public
credentials repo) → hostname `devbox-<name>` → autostop timer → awscli →
amun `tailscale` plugin → `tailscale up --login-server=https://hs.gn.al`
with the staged key → pin `pki.lan → 10.0.0.192` in `/etc/hosts` → amun
core (CA trust, ufw deny-in/allow-22, dotfiles, sshd hardening) → extra
amun plugins → `/var/lib/clouddevbox/bootstrap-complete`. Full log at
`/var/log/devbox-bootstrap.log`.

Two bootstrap facts worth knowing:

- The amun script is downloaded to `/usr/local/lib/amun-bootstrap` and run
  from there — the usual `bash <(curl …)` one-liner breaks under cloud-init
  (the polyglot needs `$0` to be a regular file or a tty on stdin). Re-run
  amun on a box with `bash /usr/local/lib/amun-bootstrap [plugin]`.
- **step-ca trust is currently NOT installed** even though the role runs:
  `10.0.0.192` is longest-prefix-shadowed by k8s-router's `10.0.0.192/27`
  MetalLB advert for every pure-tailnet client, so the pki role probes,
  times out, and skips (by design). See homelab architecture §4.15. Devboxes
  only consume LE-certed `*.lab.gn.al`, so nothing breaks.
